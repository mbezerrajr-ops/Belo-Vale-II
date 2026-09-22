"""Juntar duas fichas do mesmo animal.

A conferência de 25/08 achou vacas com duas fichas — uma com o brinco, outra
sem, cada uma com parte da produção. A correção era anular e relançar, uma
medição por vez. Juntar faz o mesmo de uma vez, com as regras de sempre:

- **A ficha que fica é a que tem o brinco.** Brinco é a identidade; duas
  fichas com brinco são dois animais, e tirar um brinco errado é um ato com
  evidência que não cabe dentro de "juntar".
- **Nada se apaga.** Cada produção ativa da ficha duplicada é relançada na
  que fica (lançamento manual de quem juntou, apontando para a original), e a
  original passa a `superseded`. A ficha duplicada fica arquivada — fora do
  rebanho, das buscas e das sugestões —, apontando para a que ficou.
- **Nada se decide em silêncio.** Produção das duas fichas no mesmo dia
  bloqueia: não há como saber qual valor vale, e quem junta resolve antes.
  Produção da duplicada depois da baixa da que fica também bloqueia.
- **O que a duplicada sabia não se perde:** campo vazio na que fica é
  preenchido; lote que a que fica não tem, ela passa a ter a partir de hoje;
  proposta pendente que apontava para a duplicada passa a apontar para a que
  ficou.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.farm_clock import farm_today
from app.db.models import (
    Animal,
    AnimalLotAssignment,
    AuditEvent,
    EventProposal,
    OfficialMeasurement,
    User,
)
from app.services.production_entry import producao_of

#: O que a ficha duplicada preenche na que fica, quando esta não tem.
#: Identidade (brinco, legacy_id) nunca passa: a duplicada guarda a dela.
FILLABLE = ("name", "nascimento", "ultimo_parto", "peso", "situacao", "observacoes", "numero_legado")

STATUS_MERGED = "Inativo"


class MergeNotFound(LookupError):
    """Uma das fichas não existe nesta fazenda."""


class MergeBlocked(ValueError):
    """A junção tem um impedimento que só uma pessoa resolve."""

    def __init__(self, blockers: list[str]) -> None:
        self.blockers = blockers
        super().__init__(" ".join(blockers))


@dataclass
class MergePlan:
    keep: Animal
    drop: Animal
    #: Produções ativas da duplicada, que serão relançadas na que fica.
    moves: list[OfficialMeasurement]
    #: (dia, litros na que fica, litros na duplicada).
    conflicts: list[tuple[date, float | None, float | None]]
    #: Campos vazios da que fica que a duplicada preenche.
    fills: dict[str, Any]
    #: Lotes vigentes da duplicada que a que fica passa a ter.
    lot_fills: list[AnimalLotAssignment]
    pending_proposals: int
    blockers: list[str]


def _label(animal: Animal) -> str:
    return f"{animal.brinco or 'sem brinco'} · {animal.name or 'sem nome'}"


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _liters(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".replace(".", ",")


async def _load(session: AsyncSession, *, farm_id: UUID, animal_id: UUID) -> Animal:
    animal = await session.scalar(
        select(Animal).where(Animal.id == animal_id, Animal.farm_id == farm_id)
    )
    if animal is None:
        raise MergeNotFound("Ficha não encontrada nesta fazenda.")
    return animal


async def _active(session: AsyncSession, animal_id: UUID, *, lock: bool = False) -> list[OfficialMeasurement]:
    query = (
        select(OfficialMeasurement)
        .where(OfficialMeasurement.animal_id == animal_id, OfficialMeasurement.status == "active")
        .order_by(OfficialMeasurement.measured_on)
    )
    if lock:
        query = query.with_for_update()
    return list(await session.scalars(query))


async def _open_lots(session: AsyncSession, animal_id: UUID) -> list[AnimalLotAssignment]:
    return list(
        await session.scalars(
            select(AnimalLotAssignment).where(
                AnimalLotAssignment.animal_id == animal_id, AnimalLotAssignment.valid_to.is_(None)
            )
        )
    )


async def plan_merge(
    session: AsyncSession, *, farm_id: UUID, animal_id: UUID, other_id: UUID, lock: bool = False
) -> MergePlan:
    """O que a junção faria — sem fazer nada. `animal_id` é a ficha em que a
    pessoa está: é ela que fica quando nenhuma das duas tem brinco."""
    one = await _load(session, farm_id=farm_id, animal_id=animal_id)
    other = await _load(session, farm_id=farm_id, animal_id=other_id)
    keep, drop = (other, one) if other.brinco and not one.brinco else (one, other)

    blockers: list[str] = []
    if one.id == other.id:
        blockers.append("Escolha a outra ficha: esta é a mesma.")
    for animal in (keep, drop):
        if animal.merged_into_id is not None:
            blockers.append(f"A ficha {_label(animal)} já foi juntada a outra.")
    if keep.brinco and drop.brinco:
        blockers.append(
            "As duas fichas têm brinco: são dois animais. Se um dos brincos está "
            "errado, tire-o na ficha (com a evidência) antes de juntar."
        )

    moves = await _active(session, drop.id, lock=lock)
    kept = {m.measured_on: m for m in await _active(session, keep.id, lock=lock)}
    conflicts = [
        (m.measured_on, producao_of(kept[m.measured_on]), producao_of(m))
        for m in moves
        if m.measured_on in kept
    ]
    if conflicts:
        dias = ", ".join(
            f"{dia:%d/%m/%Y} ({_liters(fica)} L na que fica, {_liters(sai)} L na outra)"
            for dia, fica, sai in conflicts
        )
        blockers.append(
            f"As duas fichas têm produção no mesmo dia: {dias}. Não há como saber "
            "qual vale — anule a errada antes de juntar."
        )
    if keep.exited_on is not None:
        depois = [m.measured_on for m in moves if m.measured_on > keep.exited_on]
        if depois:
            blockers.append(
                f"A ficha que fica teve baixa em {keep.exited_on:%d/%m/%Y}, e a outra tem "
                f"produção depois disso ({', '.join(f'{d:%d/%m/%Y}' for d in depois)}). "
                "Confira a baixa ou a produção antes de juntar."
            )

    fills = {
        field: getattr(drop, field)
        for field in FILLABLE
        if _empty(getattr(keep, field)) and not _empty(getattr(drop, field))
    }
    lot_fills: list[AnimalLotAssignment] = []
    if keep.exited_on is None:
        kept_kinds = {lot.kind for lot in await _open_lots(session, keep.id)}
        lot_fills = [lot for lot in await _open_lots(session, drop.id) if lot.kind not in kept_kinds]

    pending = list(
        await session.scalars(
            select(EventProposal.id).where(
                EventProposal.candidate_animal_id == drop.id, EventProposal.status == "pending"
            )
        )
    )
    return MergePlan(
        keep=keep,
        drop=drop,
        moves=moves,
        conflicts=conflicts,
        fills=fills,
        lot_fills=lot_fills,
        pending_proposals=len(pending),
        blockers=blockers,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _snapshot(measurement: OfficialMeasurement) -> dict[str, Any]:
    return {
        "animal_id": str(measurement.animal_id),
        "measured_on": measurement.measured_on.isoformat(),
        "producao": producao_of(measurement),
        "provenance": measurement.provenance,
    }


def _audit(
    session: AsyncSession,
    *,
    farm_id: UUID,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: UUID,
    previous: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_value=previous,
            new_value=new,
        )
    )


async def merge_animals(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    animal_id: UUID,
    other_id: UUID,
    reason: str,
) -> Animal:
    """Junta as duas fichas e devolve a que ficou. Faz commit."""
    plan = await plan_merge(
        session, farm_id=farm_id, animal_id=animal_id, other_id=other_id, lock=True
    )
    if plan.blockers:
        raise MergeBlocked(plan.blockers)
    keep, drop = plan.keep, plan.drop
    reason = reason.strip()
    today = farm_today()

    for original in plan.moves:
        original.status = "superseded"
        await session.flush()
        copy = OfficialMeasurement(
            animal_id=keep.id,
            measured_on=original.measured_on,
            values=dict(original.values or {}),
            status="active",
            provenance="manual_entry",
            entered_by_user_id=user.id,
            reviewed_by=user.email,
            lote_observado=original.lote_observado,
            supersedes_measurement_id=original.id,
        )
        session.add(copy)
        await session.flush()
        _audit(
            session,
            farm_id=farm_id,
            actor=user.email,
            action="measurement_moved",
            entity_type="measurement",
            entity_id=copy.id,
            previous=_snapshot(original) | {"measurement_id": str(original.id)},
            new=_snapshot(copy) | {"reason": reason, "merged_from": str(drop.id)},
        )

    lotes_duplicada = await _open_lots(session, drop.id)
    for lot in lotes_duplicada:
        lot.valid_to = max(today, lot.valid_from)
    await session.flush()
    for lot in plan.lot_fills:
        session.add(
            AnimalLotAssignment(
                animal_id=keep.id,
                lote=lot.lote,
                kind=lot.kind,
                valid_from=today,
                source="manual",
                reviewed_by=user.email,
            )
        )

    previous_keep = {field: _jsonable(getattr(keep, field)) for field in plan.fills}
    for field, value in plan.fills.items():
        setattr(keep, field, value)

    for proposal in await session.scalars(
        select(EventProposal).where(
            EventProposal.candidate_animal_id == drop.id, EventProposal.status == "pending"
        )
    ):
        proposal.candidate_animal_id = keep.id
        # Quem estava com o cartão aberto recarrega antes de aprovar.
        proposal.version += 1

    previous_drop = {"status": drop.status, "name": drop.name, "lotes": [lot.lote for lot in lotes_duplicada]}
    drop.merged_into_id = keep.id
    drop.merged_at = datetime.now(timezone.utc)
    drop.status = STATUS_MERGED

    fills = {field: _jsonable(value) for field, value in plan.fills.items()}
    detail = {
        "reason": reason,
        "moved": len(plan.moves),
        "fills": fills,
        "lots": [lot.lote for lot in plan.lot_fills],
        "pending_proposals": plan.pending_proposals,
    }
    _audit(
        session,
        farm_id=farm_id,
        actor=user.email,
        action="animal_merged",
        entity_type="animal",
        entity_id=drop.id,
        previous=previous_drop,
        new={"merged_into": str(keep.id), **detail},
    )
    _audit(
        session,
        farm_id=farm_id,
        actor=user.email,
        action="animal_absorbed",
        entity_type="animal",
        entity_id=keep.id,
        previous=previous_keep,
        new={"merged_from": str(drop.id), **detail},
    )
    await session.commit()
    return keep
