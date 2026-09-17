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
    OfficialMeasurement,
)
from app.services.baseline_snapshot import (
    EXPECTED_BASELINE,
    AnimalRecord,
    BaselineSnapshot,
    ExpectedCounts,
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

    current = await session.scalar(
        select(AnimalLotAssignment).where(
            AnimalLotAssignment.animal_id == animal.id,
            AnimalLotAssignment.valid_to.is_(None),
        )
    )
    if current is not None:
        # Já existe uma lotação vigente. A baseline não sobrescreve nem abre
        # uma segunda: uma mudança real de lote é um evento próprio.
        report.lot_assignments_skipped += 1
        return

    session.add(
        AnimalLotAssignment(
            animal_id=animal.id,
            lote=record.lote,
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
