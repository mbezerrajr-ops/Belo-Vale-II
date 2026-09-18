"""Importação da baseline legada para o PostgreSQL.

Garantias, na ordem em que importam:

- **valida antes de escrever** — um snapshot que não bate com as contagens
  conhecidas é recusado sem tocar no banco;
- **idempotente** — rodar duas vezes produz o mesmo estado, sem duplicar;
- **transacional** — falha no meio não deixa estado parcial;
- **auditável** — toda medição aponta para o registro de importação que a
  originou, e esse registro guarda o hash do arquivo de origem;
- **não migra credenciais** — usuários legados simplesmente não são lidos.

A identidade usada para reconciliar é o ``legacy_id``, não o brinco: um animal
sem brinco é migrado normalmente, apenas não fica elegível a matching
automático de arquivos futuros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Animal,
    AnimalLotAssignment,
    BaselineImport,
    Farm,
    OfficialMeasurement,
    Supply,
    SupplyDiet,
    SupplyPrice,
)
from app.services.lot_kind import KIND_DIET, classify_lot
from app.services.baseline_snapshot import (
    EXPECTED_BASELINE,
    AnimalRecord,
    BaselineSnapshot,
    ExpectedCounts,
    SupplyRecord,
    validate_snapshot,
)


@dataclass
class ImportReport:
    dry_run: bool
    baseline_import_id: UUID | None = None
    animals_created: int = 0
    animals_updated: int = 0
    animals_unchanged: int = 0
    measurements_created: int = 0
    measurements_skipped: int = 0
    lot_assignments_created: int = 0
    lot_assignments_skipped: int = 0
    supplies_created: int = 0
    supplies_updated: int = 0
    supply_prices_created: int = 0
    supply_diets_created: int = 0
    milk_price_set: bool = False
    errors: list[str] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        mode = "SIMULAÇÃO (nada foi gravado)" if self.dry_run else "APLICADO"
        lines = [
            f"modo={mode}",
            f"baseline_import_id={self.baseline_import_id}",
            f"animais criados={self.animals_created} "
            f"atualizados={self.animals_updated} "
            f"inalterados={self.animals_unchanged}",
            f"medições criadas={self.measurements_created} "
            f"já existentes={self.measurements_skipped}",
            f"lotações criadas={self.lot_assignments_created} "
            f"já vigentes={self.lot_assignments_skipped}",
            f"insumos criados={self.supplies_created} "
            f"atualizados={self.supplies_updated} "
            f"preços={self.supply_prices_created} "
            f"dietas={self.supply_diets_created}",
            f"preço do leite definido={'sim' if self.milk_price_set else 'não'}",
        ]
        lines.extend(f"ERRO: {message}" for message in self.errors)
        return lines


#: Campos cadastrais que a baseline governa. Ficam fora `identifier` (chave
#: técnica), `brinco`/`legacy_id` (identidade) e `numero_legado`, tratados
#: separadamente por serem parte da reconciliação.
_CADASTRAL_FIELDS = (
    "name",
    "situacao",
    "status",
    "ultimo_parto",
    "nascimento",
    "peso",
    "observacoes",
)


def _animal_values(record: AnimalRecord) -> dict[str, object]:
    return {
        "brinco": record.brinco,
        "brinco_origem": record.brinco_origem,
        "numero_legado": record.numero_legado,
        "name": record.name,
        "situacao": record.situacao,
        "status": record.status,
        "ultimo_parto": record.ultimo_parto,
        "nascimento": record.nascimento,
        "peso": record.peso,
        "observacoes": record.observacoes,
    }


def _differs(animal: Animal, values: dict[str, object]) -> bool:
    for key, value in values.items():
        current = getattr(animal, key)
        if key == "peso" and current is not None and value is not None:
            if float(current) != float(value):
                return True
            continue
        if current != value:
            return True
    return False


async def _resolve_baseline_import(
    session: AsyncSession,
    *,
    farm_id: UUID,
    snapshot: BaselineSnapshot,
    source_path: str,
    approved_by: str,
    notes: str | None,
) -> BaselineImport:
    """Reusa o registro do mesmo arquivo, para que reexecutar não multiplique
    a auditoria."""
    existing = await session.scalar(
        select(BaselineImport).where(
            BaselineImport.farm_id == farm_id,
            BaselineImport.source_sha256 == snapshot.source_sha256,
        )
    )
    if existing is not None:
        return existing

    record = BaselineImport(
        farm_id=farm_id,
        source_path=source_path,
        source_sha256=snapshot.source_sha256,
        animal_count=snapshot.animal_count,
        measurement_count=snapshot.measurement_count,
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc),
        notes=notes,
    )
    session.add(record)
    await session.flush()
    return record


async def import_baseline(
    session: AsyncSession,
    snapshot: BaselineSnapshot,
    *,
    farm_id: UUID,
    approved_by: str,
    reference_date: date,
    source_path: str,
    dry_run: bool = True,
    expected: ExpectedCounts | None = EXPECTED_BASELINE,
    notes: str | None = None,
) -> ImportReport:
    """Aplica a baseline na fazenda indicada.

    ``reference_date`` é a data a partir da qual a lotação observada passa a
    valer. A baseline não registra desde quando cada animal está em seu lote,
    então essa data é declarada pelo operador em vez de inferida.
    """
    report = ImportReport(dry_run=dry_run)

    errors = validate_snapshot(snapshot, expected=expected)
    if errors:
        # Recusa antes de qualquer escrita: nenhum estado parcial.
        report.errors = errors
        return report

    savepoint = await session.begin_nested()
    try:
        baseline = await _resolve_baseline_import(
            session,
            farm_id=farm_id,
            snapshot=snapshot,
            source_path=source_path,
            approved_by=approved_by,
            notes=notes,
        )
        report.baseline_import_id = baseline.id

        existing_animals = {
            animal.legacy_id: animal
            for animal in await session.scalars(
                select(Animal).where(
                    Animal.farm_id == farm_id, Animal.legacy_id.is_not(None)
                )
            )
        }

        for record in snapshot.animals:
            values = _animal_values(record)
            animal = existing_animals.get(record.legacy_id)
            if animal is None:
                animal = Animal(
                    farm_id=farm_id,
                    # `identifier` é NOT NULL e único por fazenda. O legacy_id
                    # já satisfaz as duas condições e não inventa um valor novo.
                    identifier=record.legacy_id,
                    legacy_id=record.legacy_id,
                    **values,
                )
                session.add(animal)
                await session.flush()
                existing_animals[record.legacy_id] = animal
                report.animals_created += 1
            elif _differs(animal, values):
                for key, value in values.items():
                    setattr(animal, key, value)
                report.animals_updated += 1
            else:
                report.animals_unchanged += 1

            await _apply_lot(
                session,
                animal=animal,
                record=record,
                reference_date=reference_date,
                approved_by=approved_by,
                report=report,
            )
            await _apply_measurements(
                session,
                animal=animal,
                record=record,
                baseline_id=baseline.id,
                approved_by=approved_by,
                report=report,
            )

        await _apply_supplies(
            session, farm_id=farm_id, snapshot=snapshot, actor=approved_by, report=report
        )

        await session.flush()

        if dry_run:
            await savepoint.rollback()
        else:
            await savepoint.commit()
            await session.commit()
    except Exception:
        if savepoint.is_active:
            await savepoint.rollback()
        raise

    return report


async def _apply_lot(
    session: AsyncSession,
    *,
    animal: Animal,
    record: AnimalRecord,
    reference_date: date,
    approved_by: str,
    report: ImportReport,
) -> None:
    if not record.lote:
        return

    # "LOTE 1" é lote de ordenha; "BEZERREIRO" é uma área da fazenda. A
    # baseline grava os dois no mesmo campo, e o tipo se perderia sem isto.
    kind = classify_lot(record.lote) or KIND_DIET

    current = await session.scalar(
        select(AnimalLotAssignment).where(
            AnimalLotAssignment.animal_id == animal.id,
            AnimalLotAssignment.kind == kind,
            AnimalLotAssignment.valid_to.is_(None),
        )
    )
    if current is not None:
        # Já existe uma lotação vigente deste tipo. A baseline não sobrescreve
        # nem abre uma segunda: mudança de lote é um evento próprio.
        report.lot_assignments_skipped += 1
        return

    session.add(
        AnimalLotAssignment(
            animal_id=animal.id,
            lote=record.lote,
            kind=kind,
            valid_from=reference_date,
            valid_to=None,
            source="legacy_baseline",
            reviewed_by=approved_by,
        )
    )
    report.lot_assignments_created += 1


async def _apply_measurements(
    session: AsyncSession,
    *,
    animal: Animal,
    record: AnimalRecord,
    baseline_id: UUID,
    approved_by: str,
    report: ImportReport,
) -> None:
    if not record.measurements:
        return

    existing_dates = {
        row
        for row in await session.scalars(
            select(OfficialMeasurement.measured_on).where(
                OfficialMeasurement.animal_id == animal.id,
                OfficialMeasurement.status == "active",
            )
        )
    }

    for measurement in record.measurements:
        if measurement.measured_on in existing_dates:
            # Uma medição ativa já existe para este animal e data. Substituir
            # é um ato deliberado, com motivo — nunca efeito colateral de
            # reimportar a baseline.
            report.measurements_skipped += 1
            continue
        session.add(
            OfficialMeasurement(
                animal_id=animal.id,
                measured_on=measurement.measured_on,
                values={"producao": measurement.producao},
                status="active",
                provenance="legacy_baseline",
                baseline_import_id=baseline_id,
                # O trigger exige que o responsável bata com quem aprovou a
                # importação.
                reviewed_by=approved_by,
                lote_observado=measurement.lote_observado,
            )
        )
        existing_dates.add(measurement.measured_on)
        report.measurements_created += 1


async def _apply_supplies(
    session: AsyncSession,
    *,
    farm_id: UUID,
    snapshot: BaselineSnapshot,
    actor: str,
    report: ImportReport,
) -> None:
    """Migra insumos, preços e dieta por lote.

    Reconciliado por ``legacy_id``, como os animais: reimportar atualiza em vez
    de duplicar. Preços e dietas já existentes não são recriados, porque preço
    é evento datado e a dieta é única por lote.
    """
    if snapshot.milk_price_per_liter is not None:
        farm = await session.scalar(select(Farm).where(Farm.id == farm_id))
        if farm is not None and farm.milk_price_per_liter is None:
            farm.milk_price_per_liter = snapshot.milk_price_per_liter
            report.milk_price_set = True

    existing = {
        supply.legacy_id: supply
        for supply in await session.scalars(
            select(Supply).where(Supply.farm_id == farm_id, Supply.legacy_id.is_not(None))
        )
    }

    for record in snapshot.supplies:
        supply = existing.get(record.legacy_id)
        if supply is None:
            supply = Supply(
                farm_id=farm_id,
                legacy_id=record.legacy_id,
                name=record.name,
                price_per_kg=record.price_per_kg,
            )
            session.add(supply)
            await session.flush()
            existing[record.legacy_id] = supply
            report.supplies_created += 1
        elif (
            supply.name != record.name
            or float(supply.price_per_kg) != float(record.price_per_kg)
        ):
            supply.name = record.name
            supply.price_per_kg = record.price_per_kg
            report.supplies_updated += 1

        await _apply_supply_prices(session, supply=supply, record=record, actor=actor, report=report)
        await _apply_supply_diets(session, supply=supply, record=record, report=report)


async def _apply_supply_prices(
    session: AsyncSession,
    *,
    supply: Supply,
    record: SupplyRecord,
    actor: str,
    report: ImportReport,
) -> None:
    known = {
        row
        for row in await session.scalars(
            select(SupplyPrice.effective_on).where(SupplyPrice.supply_id == supply.id)
        )
    }
    for price in record.prices:
        if price.effective_on is None or price.effective_on in known:
            continue
        session.add(
            SupplyPrice(
                supply_id=supply.id,
                price_per_kg=price.price_per_kg,
                effective_on=price.effective_on,
                source="legacy_baseline",
                recorded_by=actor,
            )
        )
        known.add(price.effective_on)
        report.supply_prices_created += 1


async def _apply_supply_diets(
    session: AsyncSession,
    *,
    supply: Supply,
    record: SupplyRecord,
    report: ImportReport,
) -> None:
    known = {
        row
        for row in await session.scalars(
            select(SupplyDiet.lote).where(SupplyDiet.supply_id == supply.id)
        )
    }
    for diet in record.diets:
        if diet.lote in known:
            continue
        session.add(
            SupplyDiet(
                supply_id=supply.id, lote=diet.lote, kg_per_day=diet.kg_per_day
            )
        )
        known.add(diet.lote)
        report.supply_diets_created += 1
