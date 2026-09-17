"""Importação da baseline legada para o PostgreSQL.

Integração real: cada teste prova uma das garantias exigidas da migração —
transacional, idempotente, auditável, sem estado parcial e sem credencial
legada.
"""

import asyncio
import os
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Animal,
    AnimalLotAssignment,
    BaselineImport,
    Farm,
    OfficialMeasurement,
    User,
)
from app.services.baseline_importer import import_baseline
from app.services.baseline_snapshot import parse_baseline

APPROVER = "titular@belovale"
REFERENCE = date(2026, 8, 25)


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _run(coroutine_factory):
    async def wrapper():
        engine = create_async_engine(_database_url())
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            return await coroutine_factory(factory)
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def _fresh_farm(session: AsyncSession, name: str) -> Farm:
    farm = Farm(name=name)
    session.add(farm)
    await session.commit()
    return farm


async def _counts(session: AsyncSession, farm_id: UUID) -> tuple[int, int, int]:
    animals = await session.scalar(
        select(func.count()).select_from(Animal).where(Animal.farm_id == farm_id)
    )
    measurements = await session.scalar(
        select(func.count())
        .select_from(OfficialMeasurement)
        .join(Animal, Animal.id == OfficialMeasurement.animal_id)
        .where(Animal.farm_id == farm_id)
    )
    lots = await session.scalar(
        select(func.count())
        .select_from(AnimalLotAssignment)
        .join(Animal, Animal.id == AnimalLotAssignment.animal_id)
        .where(Animal.farm_id == farm_id)
    )
    return animals, measurements, lots


class TestFullBaselineImport:
    def test_imports_every_animal_and_measurement(self, baseline_text: str) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Import completo")
                report = await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                assert report.errors == []
                assert report.animals_created == 401
                assert report.measurements_created == 152

                animals, measurements, _ = await _counts(session, farm.id)
                assert animals == 401
                assert measurements == 152

        _run(scenario)

    def test_measurements_keep_their_dates(self, baseline_text: str) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Datas preservadas")
                await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                rows = (
                    await session.execute(
                        select(
                            OfficialMeasurement.measured_on, func.count()
                        )
                        .join(Animal, Animal.id == OfficialMeasurement.animal_id)
                        .where(Animal.farm_id == farm.id)
                        .group_by(OfficialMeasurement.measured_on)
                    )
                ).all()
                assert dict(rows) == {date(2026, 7, 22): 107, date(2026, 8, 25): 45}

        _run(scenario)

    def test_animals_without_brinco_are_preserved(self, baseline_text: str) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Sem brinco preservado")
                await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                without = await session.scalar(
                    select(func.count())
                    .select_from(Animal)
                    .where(Animal.farm_id == farm.id, Animal.brinco.is_(None))
                )
                assert without == 142

        _run(scenario)

    def test_unreadable_brinco_is_recorded_as_observation(
        self, baseline_text: str
    ) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Brinco ilegivel")
                await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                serrana = await session.scalar(
                    select(Animal).where(
                        Animal.farm_id == farm.id,
                        Animal.legacy_id == "v-b2-xxx-serrana",
                    )
                )
                assert serrana is not None
                assert serrana.brinco is None
                assert serrana.brinco_origem == "B2-XXX"
                assert "B2-XXX" in (serrana.observacoes or "")
                # As duas medições dela continuam válidas.
                count = await session.scalar(
                    select(func.count())
                    .select_from(OfficialMeasurement)
                    .where(OfficialMeasurement.animal_id == serrana.id)
                )
                assert count == 2

        _run(scenario)

    def test_colliding_legacy_numbers_become_separate_animals(
        self, baseline_text: str
    ) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Numeros colidentes")
                await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                same_number = await session.scalar(
                    select(func.count())
                    .select_from(Animal)
                    .where(Animal.farm_id == farm.id, Animal.numero_legado == "346")
                )
                assert same_number == 2

        _run(scenario)

    def test_lot_history_is_created_for_animals_with_a_lot(
        self, baseline_text: str
    ) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Historico de lote")
                report = await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                assert report.lot_assignments_created == 283
                row = await session.scalar(
                    select(AnimalLotAssignment)
                    .join(Animal, Animal.id == AnimalLotAssignment.animal_id)
                    .where(Animal.farm_id == farm.id)
                    .limit(1)
                )
                assert row.source == "legacy_baseline"
                assert row.valid_from == REFERENCE
                assert row.valid_to is None

        _run(scenario)

    def test_measurements_declare_baseline_provenance(
        self, baseline_text: str
    ) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Proveniencia")
                await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                non_baseline = await session.scalar(
                    select(func.count())
                    .select_from(OfficialMeasurement)
                    .join(Animal, Animal.id == OfficialMeasurement.animal_id)
                    .where(
                        Animal.farm_id == farm.id,
                        OfficialMeasurement.provenance != "legacy_baseline",
                    )
                )
                assert non_baseline == 0

                record = await session.scalar(
                    select(BaselineImport).where(BaselineImport.farm_id == farm.id)
                )
                assert record.animal_count == 401
                assert record.measurement_count == 152
                assert record.approved_by == APPROVER
                assert len(record.source_sha256) == 64

        _run(scenario)


class TestIdempotency:
    def test_running_twice_does_not_duplicate(self, baseline_text: str) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Idempotencia")
                snapshot = parse_baseline(baseline_text)
                kwargs = dict(
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                await import_baseline(session, snapshot, **kwargs)
                first = await _counts(session, farm.id)

                second_report = await import_baseline(session, snapshot, **kwargs)
                second = await _counts(session, farm.id)

                assert first == second == (401, 152, 283)
                assert second_report.animals_created == 0
                assert second_report.measurements_created == 0
                assert second_report.lot_assignments_created == 0

        _run(scenario)

    def test_second_run_reuses_the_same_baseline_import(
        self, baseline_text: str
    ) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Reuso do registro")
                snapshot = parse_baseline(baseline_text)
                kwargs = dict(
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                first = await import_baseline(session, snapshot, **kwargs)
                second = await import_baseline(session, snapshot, **kwargs)
                assert first.baseline_import_id == second.baseline_import_id
                total = await session.scalar(
                    select(func.count())
                    .select_from(BaselineImport)
                    .where(BaselineImport.farm_id == farm.id)
                )
                assert total == 1

        _run(scenario)


class TestDryRun:
    def test_dry_run_writes_nothing(self, baseline_text: str) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Dry run")
                report = await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=True,
                )
                assert report.dry_run is True
                assert report.animals_created == 401
                assert report.measurements_created == 152

            # Sessão nova: garante que nada foi persistido.
            async with factory() as verification:
                assert await _counts(verification, farm.id) == (0, 0, 0)

        _run(scenario)


class TestFailureLeavesNoPartialState:
    def test_invalid_snapshot_is_rejected_before_writing(
        self, baseline_text: str
    ) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _fresh_farm(session, "Snapshot invalido")
                snapshot = parse_baseline(baseline_text)
                broken = snapshot.__class__(
                    animals=snapshot.animals[:10],  # contagem não bate
                    source_sha256=snapshot.source_sha256,
                )
                report = await import_baseline(
                    session,
                    broken,
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                assert report.errors
                assert report.animals_created == 0

            async with factory() as verification:
                assert await _counts(verification, farm.id) == (0, 0, 0)

        _run(scenario)


class TestNoLegacyCredentials:
    def test_import_creates_no_users(self, baseline_text: str) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                before = await session.scalar(select(func.count()).select_from(User))
                farm = await _fresh_farm(session, "Sem usuarios")
                await import_baseline(
                    session,
                    parse_baseline(baseline_text),
                    farm_id=farm.id,
                    approved_by=APPROVER,
                    reference_date=REFERENCE,
                    source_path="state_canonical.json",
                    dry_run=False,
                )
                after = await session.scalar(select(func.count()).select_from(User))
                assert before == after

        _run(scenario)
