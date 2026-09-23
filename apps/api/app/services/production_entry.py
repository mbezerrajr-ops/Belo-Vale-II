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


class ImplausibleValue(ProductionEntryError):
    """Litros fora do plausível ou ausentes."""


class MilkingsDoNotAddUp(ImplausibleValue):
    """Manhã + tarde diferente do total informado."""


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


#: As duas ordenhas do dia, guardadas no `values` da leitura ao lado do total.
MILKINGS = ("manha", "tarde")


def milkings_of(measurement: OfficialMeasurement) -> dict[str, float]:
    """Manhã e tarde que a leitura tem. Leituras antigas têm só o total."""
    values = measurement.values or {}
    found = {}
    for key in MILKINGS:
        try:
            if values.get(key) is not None:
                found[key] = float(values[key])
        except (TypeError, ValueError):
            continue
    return found


def clean_note(observacao: str | None) -> str | None:
    """Anotação sem espaços sobrando; vazia vira ``None``."""
    if observacao is None:
        return None
    cleaned = " ".join(observacao.split())
    return cleaned[:200] or None


@dataclass(frozen=True)
class EntryResult:
    measurement: OfficialMeasurement
    created: bool


def _check_plausible(producao: float) -> float:
    # A validação do schema já barra isto; repetir aqui mantém o serviço
    # seguro para quem o chamar sem passar pela API.
    if producao < 0 or producao > MAX_LITERS:
        raise ImplausibleValue(
            f"Produção fora do plausível (0 a {MAX_LITERS:g} L). Confira o valor."
        )
    return round(float(producao), 2)


def reading_values(
    *, producao: float | None = None, manha: float | None = None, tarde: float | None = None
) -> dict[str, float]:
    """O `values` de uma leitura: o total e, quando houver, as ordenhas.

    Com manhã ou tarde, o total é a soma delas; um total informado junto
    precisa bater com ela (a planilha em que 15,5 + 14 dá "29" é recusada,
    não arredondada).
    """
    milkings = {
        key: _check_plausible(value)
        for key, value in (("manha", manha), ("tarde", tarde))
        if value is not None
    }
    if not milkings:
        if producao is None:
            raise ImplausibleValue("Informe os litros: manhã, tarde ou o total do dia.")
        return {"producao": _check_plausible(producao)}
    soma = round(sum(milkings.values()), 2)
    if producao is not None and abs(float(producao) - soma) > 0.05:
        raise MilkingsDoNotAddUp(
            f"Manhã + tarde dá {soma:g} L, e o total informado é {float(producao):g} L. "
            "Confira os valores."
        )
    return {"producao": _check_plausible(soma), **milkings}


def _normalized(measurement: OfficialMeasurement) -> dict[str, float]:
    return {"producao": producao_of(measurement), **milkings_of(measurement)}


def merge_reading(
    existing: OfficialMeasurement, values: dict[str, float], observacao: str | None
) -> tuple[dict[str, float], str | None] | None:
    """A leitura que resulta de acrescentar `values` e a anotação à existente.

    Acrescentar é preencher o que falta: a tarde de quem só tinha a manhã, as
    duas ordenhas de uma leitura antiga só com o total (se somarem o mesmo), a
    anotação de quem não tinha. Mudar o que já está lançado não é acrescentar:
    devolve ``None``, e quem chamou trata como conflito.
    """
    old_milkings = milkings_of(existing)
    new_milkings = {key: values[key] for key in MILKINGS if key in values}
    total = producao_of(existing)

    if not new_milkings:
        if values["producao"] != total:
            return None
        merged = _normalized(existing)
    elif not old_milkings:
        if len(new_milkings) < len(MILKINGS) or values["producao"] != total:
            return None
        merged = dict(values)
    else:
        combined = dict(old_milkings)
        for key, value in new_milkings.items():
            if key in combined and combined[key] != value:
                return None
            combined[key] = value
        merged = {"producao": _check_plausible(sum(combined.values())), **combined}

    note = existing.observacao
    if observacao and note and observacao != note:
        return None
    return merged, note or observacao


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
        **milkings_of(measurement),
        "observacao": measurement.observacao,
        "provenance": measurement.provenance,
    }


async def record_reading(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    animal_id: UUID,
    measured_on: date,
    producao: float | None = None,
    manha: float | None = None,
    tarde: float | None = None,
    observacao: str | None = None,
) -> EntryResult:
    """Lança a produção de uma vaca num dia. Não faz commit.

    Se a vaca já tem leitura na data, repetir é inofensivo e completar o que
    falta (a tarde, a anotação) cria uma versão nova; mudar o que já está
    lançado é conflito.
    """
    values = reading_values(producao=producao, manha=manha, tarde=tarde)
    observacao = clean_note(observacao)
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
        merged = merge_reading(existing, values, observacao)
        if merged is None:
            raise ConflictingReading(existing)
        merged_values, merged_note = merged
        if merged_values == _normalized(existing) and merged_note == existing.observacao:
            return EntryResult(measurement=existing, created=False)
        completed = await supersede(
            session,
            farm_id=farm_id,
            user=user,
            previous=existing,
            values=merged_values,
            observacao=merged_note,
            action="measurement_completed",
        )
        return EntryResult(measurement=completed, created=True)

    measurement = OfficialMeasurement(
        animal_id=animal_id,
        measured_on=measured_on,
        values=values,
        observacao=observacao,
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


async def supersede(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    previous: OfficialMeasurement,
    values: dict[str, float],
    observacao: str | None,
    action: str,
    reason: str | None = None,
    production_import_id: UUID | None = None,
) -> OfficialMeasurement:
    """Nova versão de uma leitura ativa; a anterior fica no histórico.

    Com `production_import_id`, a versão nova aponta para o arquivo que a
    completou; sem ele, é lançamento de quem está na tela.
    """
    previous.status = "superseded"
    # O índice único parcial permite uma ativa por vaca e data: a antiga
    # precisa deixar de ser ativa antes de a nova ser inserida.
    await session.flush()

    replacement = OfficialMeasurement(
        animal_id=previous.animal_id,
        measured_on=previous.measured_on,
        values=values,
        observacao=observacao,
        status="active",
        provenance="file_import" if production_import_id else "manual_entry",
        production_import_id=production_import_id,
        entered_by_user_id=None if production_import_id else user.id,
        reviewed_by=user.email,
        lote_observado=previous.lote_observado,
        supersedes_measurement_id=previous.id,
    )
    session.add(replacement)
    await session.flush()
    new = _snapshot(replacement)
    if reason is not None:
        new["reason"] = reason
    _audit(
        session,
        farm_id=farm_id,
        actor=user.email,
        action=action,
        measurement_id=replacement.id,
        previous=_snapshot(previous) | {"measurement_id": str(previous.id)},
        new=new,
    )
    return replacement


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


#: Na correção, "não mexer na anotação" é diferente de "apagar a anotação".
KEEP_NOTE = object()


async def correct_reading(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    measurement_id: UUID,
    reason: str,
    producao: float | None = None,
    manha: float | None = None,
    tarde: float | None = None,
    observacao: str | None | object = KEEP_NOTE,
) -> OfficialMeasurement:
    """Substitui o valor de uma leitura ativa. Não faz commit."""
    values = reading_values(producao=producao, manha=manha, tarde=tarde)
    previous = await _load_active_for_change(
        session, farm_id=farm_id, measurement_id=measurement_id
    )
    note = previous.observacao if observacao is KEEP_NOTE else clean_note(observacao)  # type: ignore[arg-type]
    if values == _normalized(previous) and note == previous.observacao:
        raise NothingToCorrect("O valor informado é igual ao já lançado.")
    return await supersede(
        session,
        farm_id=farm_id,
        user=user,
        previous=previous,
        values=values,
        observacao=note,
        action="measurement_corrected",
        reason=reason,
    )


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
    #: A pesagem mais recente antes do dia: referência na folha em branco.
    previous: OfficialMeasurement | None = None


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
    previous = {
        m.animal_id: m
        for m in await session.scalars(
            select(OfficialMeasurement)
            .where(
                OfficialMeasurement.animal_id.in_([a.id for a in animals]),
                OfficialMeasurement.measured_on < measured_on,
                OfficialMeasurement.status == "active",
            )
            .distinct(OfficialMeasurement.animal_id)
            .order_by(OfficialMeasurement.animal_id, OfficialMeasurement.measured_on.desc())
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
            previous=previous.get(a.id),
        )
        for a in animals
    ]
