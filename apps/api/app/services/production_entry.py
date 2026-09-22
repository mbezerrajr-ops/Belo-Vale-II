"""Lançamento manual de produção de leite.

É o caminho do dia a dia: o funcionário anota a produção de cada vaca e lança
do celular. Três regras sustentam a confiança no dado:

- **Um lançamento por vaca e data.** Reenviar o mesmo valor é inofensivo
  (retry do celular); um valor diferente nunca sobrescreve em silêncio.
- **Corrigir é um ato separado**, de revisor ou administrador, com motivo. A
  versão anterior fica no banco como `superseded`, apontada pela nova.
- **Anular** serve para o lançamento feito na vaca errada, onde não há valor
  certo a pôr no lugar. A linha fica como `voided` e libera a data.

Nada disso apaga linha: histórico de produção é prova, não rascunho.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.farm_clock import farm_today
from app.db.models import Animal, AnimalLotAssignment, AuditEvent, OfficialMeasurement, User
from app.services.lot_kind import KIND_DIET

#: Teto de plausibilidade, em litros por vaca por dia. Acima disso é quase
#: certamente erro de digitação (215 em vez de 21,5); a maior produção da
#: baseline é 37,5 L.
MAX_LITERS = 80.0


class ProductionEntryError(ValueError):
    """Lançamento recusado por uma regra de negócio."""


class AnimalNotFound(ProductionEntryError):
    pass


class MeasurementNotFound(ProductionEntryError):
    pass


class AnimalHasLeft(ProductionEntryError):
    pass


class FutureDate(ProductionEntryError):
    pass


class NotActive(ProductionEntryError):
    pass


class NothingToCorrect(ProductionEntryError):
    pass


class ConflictingReading(ProductionEntryError):
    """Já existe uma leitura ativa com outro valor."""

    def __init__(self, existing: OfficialMeasurement) -> None:
        super().__init__(
            "Esta vaca já tem produção lançada nesta data, com outro valor. "
            "Para mudar, peça a correção a um revisor ou administrador."
        )
        self.existing = existing


def producao_of(measurement: OfficialMeasurement) -> float | None:
    """A baseline e o lançamento gravam `producao`; o OCR grava `total`."""
    values = measurement.values or {}
    for key in ("producao", "total"):
        if values.get(key) is not None:
            try:
                return float(values[key])
            except (TypeError, ValueError):
                return None
    return None


@dataclass(frozen=True)
class EntryResult:
    measurement: OfficialMeasurement
    created: bool


def _check_plausible(producao: float) -> float:
    # A validação do schema já barra isto; repetir aqui mantém o serviço
    # seguro para quem o chamar sem passar pela API.
    if producao < 0 or producao > MAX_LITERS:
        raise ProductionEntryError(
            f"Produção fora do plausível (0 a {MAX_LITERS:g} L). Confira o valor."
        )
    return round(float(producao), 2)


async def _load_animal(session: AsyncSession, *, farm_id: UUID, animal_id: UUID) -> Animal:
    animal = await session.scalar(
        select(Animal).where(Animal.id == animal_id, Animal.farm_id == farm_id)
    )
    if animal is None:
        raise AnimalNotFound("Animal não encontrado.")
    if animal.merged_into_id is not None:
        raise AnimalNotFound("Esta ficha foi juntada a outra: lance a produção na ficha que ficou.")
    return animal


async def _active_reading(
    session: AsyncSession, *, animal_id: UUID, measured_on: date
) -> OfficialMeasurement | None:
    return await session.scalar(
        select(OfficialMeasurement)
        .where(
            OfficialMeasurement.animal_id == animal_id,
            OfficialMeasurement.measured_on == measured_on,
            OfficialMeasurement.status == "active",
        )
        # Trava a linha: dois lançamentos simultâneos para a mesma vaca não
        # podem ambos concluir que ela está livre.
        .with_for_update()
    )


async def diet_lot_on(
    session: AsyncSession, *, animal_id: UUID, day: date
) -> str | None:
    """Lote de ordenha em que o animal estava naquele dia."""
    return await session.scalar(
        select(AnimalLotAssignment.lote).where(
            AnimalLotAssignment.animal_id == animal_id,
            AnimalLotAssignment.kind == KIND_DIET,
            AnimalLotAssignment.valid_from <= day,
            (AnimalLotAssignment.valid_to.is_(None))
            | (AnimalLotAssignment.valid_to >= day),
        )
    )


def _audit(
    session: AsyncSession,
    *,
    farm_id: UUID,
    actor: str,
    action: str,
    measurement_id: UUID,
    previous: dict | None = None,
    new: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=actor,
            action=action,
            entity_type="measurement",
            entity_id=measurement_id,
            previous_value=previous,
            new_value=new,
        )
    )


def _snapshot(measurement: OfficialMeasurement) -> dict:
    return {
        "animal_id": str(measurement.animal_id),
        "measured_on": measurement.measured_on.isoformat(),
        "producao": producao_of(measurement),
        "provenance": measurement.provenance,
    }


async def record_reading(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    animal_id: UUID,
    measured_on: date,
    producao: float,
) -> EntryResult:
    """Lança a produção de uma vaca num dia. Não faz commit."""
    producao = _check_plausible(producao)
    if measured_on > farm_today():
        raise FutureDate("A data da coleta não pode ser no futuro.")

    animal = await _load_animal(session, farm_id=farm_id, animal_id=animal_id)
    if animal.exited_on is not None and measured_on > animal.exited_on:
        raise AnimalHasLeft(
            f"Este animal teve baixa em {animal.exited_on:%d/%m/%Y}; "
            "não recebe produção depois dessa data."
        )

    existing = await _active_reading(
        session, animal_id=animal_id, measured_on=measured_on
    )
    if existing is not None:
        if producao_of(existing) == producao:
            return EntryResult(measurement=existing, created=False)
        raise ConflictingReading(existing)

    measurement = OfficialMeasurement(
        animal_id=animal_id,
        measured_on=measured_on,
        values={"producao": producao},
        status="active",
        provenance="manual_entry",
        entered_by_user_id=user.id,
        reviewed_by=user.email,
        lote_observado=await diet_lot_on(
            session, animal_id=animal_id, day=measured_on
        ),
    )
    session.add(measurement)
    await session.flush()
    _audit(
        session,
        farm_id=farm_id,
        actor=user.email,
        action="measurement_entered",
        measurement_id=measurement.id,
        new=_snapshot(measurement),
    )
    return EntryResult(measurement=measurement, created=True)


async def _load_active_for_change(
    session: AsyncSession, *, farm_id: UUID, measurement_id: UUID
) -> OfficialMeasurement:
    measurement = await session.scalar(
        select(OfficialMeasurement)
        .join(Animal, Animal.id == OfficialMeasurement.animal_id)
        .where(OfficialMeasurement.id == measurement_id, Animal.farm_id == farm_id)
        .with_for_update(of=OfficialMeasurement)
    )
    if measurement is None:
        raise MeasurementNotFound("Lançamento não encontrado.")
    if measurement.status != "active":
        raise NotActive(
            "Este lançamento já foi corrigido ou anulado. Abra a versão atual."
        )
    return measurement


async def correct_reading(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    measurement_id: UUID,
    producao: float,
    reason: str,
) -> OfficialMeasurement:
    """Substitui o valor de uma leitura ativa. Não faz commit."""
    producao = _check_plausible(producao)
    previous = await _load_active_for_change(
        session, farm_id=farm_id, measurement_id=measurement_id
    )
    if producao_of(previous) == producao:
        raise NothingToCorrect("O valor informado é igual ao já lançado.")

    previous.status = "superseded"
    # O índice único parcial permite uma ativa por vaca e data: a antiga
    # precisa deixar de ser ativa antes de a nova ser inserida.
    await session.flush()

    corrected = OfficialMeasurement(
        animal_id=previous.animal_id,
        measured_on=previous.measured_on,
        values={"producao": producao},
        status="active",
        provenance="manual_entry",
        entered_by_user_id=user.id,
        reviewed_by=user.email,
        lote_observado=previous.lote_observado,
        supersedes_measurement_id=previous.id,
    )
    session.add(corrected)
    await session.flush()
    _audit(
        session,
        farm_id=farm_id,
        actor=user.email,
        action="measurement_corrected",
        measurement_id=corrected.id,
        previous=_snapshot(previous) | {"measurement_id": str(previous.id)},
        new=_snapshot(corrected) | {"reason": reason},
    )
    return corrected


async def void_reading(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    measurement_id: UUID,
    reason: str,
) -> None:
    """Anula uma leitura ativa sem pôr outra no lugar. Não faz commit."""
    measurement = await _load_active_for_change(
        session, farm_id=farm_id, measurement_id=measurement_id
    )
    measurement.status = "voided"
    await session.flush()
    _audit(
        session,
        farm_id=farm_id,
        actor=user.email,
        action="measurement_voided",
        measurement_id=measurement.id,
        previous=_snapshot(measurement),
        new={"status": "voided", "reason": reason},
    )


@dataclass(frozen=True)
class SheetRow:
    animal_id: UUID
    brinco: str | None
    name: str | None
    situacao: str | None
    measurement: OfficialMeasurement | None


async def milking_lots(session: AsyncSession, *, farm_id: UUID) -> list[str]:
    """Lotes de ordenha com ao menos um animal no rebanho hoje."""
    rows = await session.scalars(
        select(AnimalLotAssignment.lote)
        .join(Animal, Animal.id == AnimalLotAssignment.animal_id)
        .where(
            Animal.farm_id == farm_id,
            Animal.exited_on.is_(None),
            AnimalLotAssignment.kind == KIND_DIET,
            AnimalLotAssignment.valid_to.is_(None),
        )
        .distinct()
    )
    return sorted(rows)


async def build_sheet(
    session: AsyncSession, *, farm_id: UUID, lote: str, measured_on: date
) -> list[SheetRow]:
    """A folha de coleta: as vacas do lote hoje e o que já foi lançado no dia."""
    animals = list(
        await session.scalars(
            select(Animal)
            .join(AnimalLotAssignment, AnimalLotAssignment.animal_id == Animal.id)
            .where(
                Animal.farm_id == farm_id,
                Animal.exited_on.is_(None),
                AnimalLotAssignment.kind == KIND_DIET,
                AnimalLotAssignment.lote == lote,
                AnimalLotAssignment.valid_to.is_(None),
            )
        )
    )
    readings = {
        m.animal_id: m
        for m in await session.scalars(
            select(OfficialMeasurement).where(
                OfficialMeasurement.animal_id.in_([a.id for a in animals]),
                OfficialMeasurement.measured_on == measured_on,
                OfficialMeasurement.status == "active",
            )
        )
    }
    # Ordem do caderno: pelo brinco, e os sem brinco no fim, por nome.
    animals.sort(key=lambda a: (a.brinco is None, a.brinco or "", a.name or ""))
    return [
        SheetRow(
            animal_id=a.id,
            brinco=a.brinco,
            name=a.name,
            situacao=a.situacao,
            measurement=readings.get(a.id),
        )
        for a in animals
    ]
