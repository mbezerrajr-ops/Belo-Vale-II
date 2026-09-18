"""Lançamento manual de produção de leite.

Lançar é tarefa de qualquer conta (operador para cima). Corrigir e anular
mudam um dado já registrado e por isso exigem revisor ou administrador.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import Farm, OfficialMeasurement, User
from app.db.session import get_db_session
from app.routers.registry import resolve_current_farm
from app.schemas.production import (
    CorrectionIn,
    ReadingIn,
    ReadingOut,
    SheetItem,
    SheetOut,
    VoidIn,
)
from app.services import production_entry as entry
from app.services.production_entry import (
    AnimalNotFound,
    ConflictingReading,
    FutureDate,
    MeasurementNotFound,
    ProductionEntryError,
    producao_of,
)

router = APIRouter(prefix="/api/production", tags=["production"])


def _out(measurement: OfficialMeasurement) -> ReadingOut:
    return ReadingOut(
        id=measurement.id,
        animal_id=measurement.animal_id,
        measured_on=measurement.measured_on,
        producao=producao_of(measurement),
        provenance=measurement.provenance,
        entered_by=measurement.reviewed_by,
        supersedes=measurement.supersedes_measurement_id,
        created_at=measurement.created_at,
    )


def _http_error(error: ProductionEntryError) -> HTTPException:
    if isinstance(error, (AnimalNotFound, MeasurementNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, FutureDate):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, ConflictingReading):
        # O valor existente vai junto: a tela mostra o que já está lançado em
        # vez de só dizer "conflito".
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "existing": _out(error.existing).model_dump(mode="json"),
            },
        )
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))


@router.get("/sheet", response_model=SheetOut)
async def production_sheet(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    measured_on: date,
    lote: Annotated[str, Query(min_length=1, max_length=64)],
) -> SheetOut:
    rows = await entry.build_sheet(
        session, farm_id=farm.id, lote=lote, measured_on=measured_on
    )
    return SheetOut(
        measured_on=measured_on,
        lote=lote,
        lotes=await entry.milking_lots(session, farm_id=farm.id),
        items=[
            SheetItem(
                animal_id=row.animal_id,
                brinco=row.brinco,
                name=row.name,
                situacao=row.situacao,
                producao=producao_of(row.measurement) if row.measurement else None,
                measurement_id=row.measurement.id if row.measurement else None,
                provenance=row.measurement.provenance if row.measurement else None,
            )
            for row in rows
        ],
    )


@router.post("", response_model=ReadingOut, status_code=status.HTTP_201_CREATED)
async def enter_reading(
    payload: ReadingIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("operator"))],
) -> ReadingOut:
    for attempt in range(2):
        try:
            result = await entry.record_reading(
                session,
                farm_id=farm.id,
                user=user,
                animal_id=payload.animal_id,
                measured_on=payload.measured_on,
                producao=payload.producao,
            )
            await session.commit()
            break
        except ProductionEntryError as error:
            # A resposta lê o registro existente: montada antes do rollback,
            # que expira os objetos da sessão.
            failure = _http_error(error)
            await session.rollback()
            raise failure from error
        except IntegrityError:
            # Dois lançamentos simultâneos para a mesma vaca e data: o índice
            # único barrou o segundo. Uma nova tentativa enxerga o primeiro e
            # responde como retry (mesmo valor) ou conflito (outro valor).
            await session.rollback()
            if attempt == 1:
                raise
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _out(result.measurement)


@router.post(
    "/{measurement_id}/correction",
    response_model=ReadingOut,
    status_code=status.HTTP_201_CREATED,
)
async def correct_reading(
    measurement_id: UUID,
    payload: CorrectionIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> ReadingOut:
    try:
        corrected = await entry.correct_reading(
            session,
            farm_id=farm.id,
            user=user,
            measurement_id=measurement_id,
            producao=payload.producao,
            reason=payload.reason,
        )
    except ProductionEntryError as error:
        failure = _http_error(error)
        await session.rollback()
        raise failure from error
    await session.commit()
    return _out(corrected)


@router.post("/{measurement_id}/void", status_code=status.HTTP_204_NO_CONTENT)
async def void_reading(
    measurement_id: UUID,
    payload: VoidIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> Response:
    try:
        await entry.void_reading(
            session,
            farm_id=farm.id,
            user=user,
            measurement_id=measurement_id,
            reason=payload.reason,
        )
    except ProductionEntryError as error:
        failure = _http_error(error)
        await session.rollback()
        raise failure from error
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
