"""Caixa de revisão: propostas de eventos lidas de fotos, áudios e textos.

Qualquer conta vê a caixa; decidir (aprovar ou rejeitar) é de revisor ou
administrador, como as demais mudanças de cadastro. Toda decisão leva a
versão que a pessoa viu: se outra pessoa decidiu antes, a segunda é recusada
em vez de sobrescrever.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import Farm, MediaAsset, User
from app.db.session import get_db_session
from app.routers.registry import resolve_current_farm
from app.services.storage import ObjectStorage, get_object_storage
from app.services.animal_registry import AnimalRegistryError
from app.services.event_proposals import (
    ProposalAlreadyDecided,
    ProposalError,
    ProposalInvalid,
    ProposalNotFound,
    ProposalStale,
    ReplacementRequired,
    animal_summary,
    approve_proposal,
    list_proposals,
    redate_source,
    reject_proposal,
)
from app.services.production_entry import producao_of

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

#: Validade do link da foto na revisão, como nos recortes da ficha.
_PHOTO_URL_TTL_SECONDS = 900


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    animal_id: UUID
    payload: dict[str, Any]
    #: Obrigatório só quando a produção substitui outra já lançada.
    replace_reason: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _required(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Explique em poucas palavras por que rejeitar.")
        return value.strip()


class SourceDateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_date: date


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProposalNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ReplacementRequired):
        existing = error.existing
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "existing": {
                    "id": str(existing.id),
                    "producao": producao_of(existing),
                    "provenance": existing.provenance,
                    "entered_by": existing.reviewed_by,
                },
            },
        )
    if isinstance(error, (ProposalAlreadyDecided, ProposalStale, AnimalRegistryError)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, ProposalInvalid):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))


@router.get("")
async def inbox(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    status_: Annotated[
        Literal["pending", "approved", "rejected"], Query(alias="status")
    ] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[dict[str, Any]]:
    items = await list_proposals(session, farm_id=farm.id, status=status_, limit=limit)

    photos: dict[UUID, str | None] = {}

    async def photo_url(source) -> str | None:
        if source.media_asset_id is None:
            return None
        if source.media_asset_id not in photos:
            image = await session.get(MediaAsset, source.media_asset_id)
            photos[source.media_asset_id] = (
                storage.presigned_url(image.object_key, expires_seconds=_PHOTO_URL_TTL_SECONDS)
                if image is not None and image.object_key
                else None
            )
        return photos[source.media_asset_id]
    summaries: dict[UUID, dict[str, Any]] = {}

    async def summary(animal):
        if animal.id not in summaries:
            summaries[animal.id] = await animal_summary(session, animal)
        return summaries[animal.id]

    out = []
    for item in items:
        proposal, source = item.proposal, item.source
        out.append(
            {
                "id": str(proposal.id),
                "source": {
                    "id": str(source.id),
                    "kind": source.kind,
                    "label": source.label,
                    # A data que vale (corrigida, se alguém corrigiu) e a lida.
                    "reference_date": _iso(source.effective_reference_date),
                    "reference_date_read": _iso(source.reference_date),
                    "corrected_by": item.corrected_by,
                    "extractor_name": source.extractor_name,
                    "created_at": source.created_at.isoformat(),
                    # A folha que deu origem à leitura, para conferir sem
                    # trocar de tela. Link curto: 15 minutos.
                    "photo_url": await photo_url(source),
                },
                "position": proposal.position,
                "event_type": proposal.event_type,
                "brinco_lido": proposal.brinco_lido,
                "nome_lido": proposal.nome_lido,
                "candidate": await summary(item.candidate) if item.candidate else None,
                "name_suggestions": [await summary(a) for a in item.suggestions],
                "payload": proposal.payload,
                "raw_fields": proposal.raw_fields,
                "evidence": proposal.evidence,
                "confidence": proposal.confidence,
                "alerts": proposal.alerts,
                "status": proposal.status,
                "version": proposal.version,
                "decided_by": item.decided_by,
                "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
                "decision_reason": proposal.decision_reason,
                "applied_payload": proposal.applied_payload,
                "result": proposal.result,
            }
        )
    return out


@router.post("/{proposal_id}/approve")
async def approve(
    proposal_id: UUID,
    body: ApproveIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> dict[str, Any]:
    try:
        result = await approve_proposal(
            session,
            farm_id=farm.id,
            user=user,
            proposal_id=proposal_id,
            expected_version=body.expected_version,
            animal_id=body.animal_id,
            payload=body.payload,
            replace_reason=body.replace_reason,
        )
        await session.commit()
    except (ProposalError, AnimalRegistryError) as error:
        # A resposta pode ler o registro existente: montada antes do rollback.
        failure = _http_error(error)
        await session.rollback()
        raise failure from error
    return {"id": str(proposal_id), "status": "approved", "result": result}


@router.post("/{proposal_id}/reject")
async def reject(
    proposal_id: UUID,
    body: RejectIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> dict[str, Any]:
    try:
        await reject_proposal(
            session,
            farm_id=farm.id,
            user=user,
            proposal_id=proposal_id,
            expected_version=body.expected_version,
            reason=body.reason,
        )
        await session.commit()
    except ProposalError as error:
        failure = _http_error(error)
        await session.rollback()
        raise failure from error
    return {"id": str(proposal_id), "status": "rejected"}


@router.post("/sources/{source_id}/date")
async def correct_source_date(
    source_id: UUID,
    body: SourceDateIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> dict[str, Any]:
    """Troca a data de um arquivo inteiro: todas as propostas pendentes dele."""
    try:
        result = await redate_source(
            session, farm_id=farm.id, user=user, source_id=source_id, new_date=body.reference_date
        )
        await session.commit()
    except ProposalError as error:
        failure = _http_error(error)
        await session.rollback()
        raise failure from error
    return {"updated": result.updated, "kept_decided": result.kept_decided}
