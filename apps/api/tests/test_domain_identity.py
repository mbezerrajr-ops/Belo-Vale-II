"""Garantias de schema do modelo de identidade e do histórico de lotação.

Estes testes existem para provar que o banco, e não apenas o código de
aplicação, impede os estados que a regra de negócio proíbe.
"""

import asyncio
import os
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
# O trigger de proveniência levanta RaiseError (DBAPIError); as constraints
# levantam IntegrityError, que é subclasse de DBAPIError. Usar a superclasse
# cobre os dois caminhos de rejeição.
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Animal,
    AnimalLotAssignment,
    BaselineImport,
    ExtractedLine,
    ExtractionRun,
    Farm,
    ImageAsset,
    Import,
    OfficialMeasurement,
    ReviewDecision,
)


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


async def _session_factory():
    engine = create_async_engine(_database_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _make_farm(session: AsyncSession, name: str = "Belo Vale II") -> Farm:
    farm = Farm(name=name)
    session.add(farm)
    await session.commit()
    return farm


async def _make_baseline_import(session: AsyncSession, farm_id: UUID) -> BaselineImport:
    baseline = BaselineImport(
        farm_id=farm_id,
        source_path="belo-vale-ii-projeto-completo/plataforma/state_canonical.json",
        source_sha256="0" * 64,
        animal_count=401,
        measurement_count=152,
        approved_by="titular",
        approved_at=datetime.now(timezone.utc),
    )
    session.add(baseline)
    await session.commit()
    return baseline


async def _make_review_decision(session: AsyncSession, farm_id: UUID) -> ReviewDecision:
    ingestion = Import(farm_id=farm_id)
    session.add(ingestion)
    await session.flush()
    asset = ImageAsset(farm_id=farm_id, import_id=ingestion.id, sha256="b" * 64)
    session.add(asset)
    await session.flush()
    run = ExtractionRun(image_asset_id=asset.id)
    session.add(run)
    await session.flush()
    line = ExtractedLine(extraction_run_id=run.id, line_number=1, raw_values={})
    session.add(line)
    await session.flush()
    decision = ReviewDecision(extracted_line_id=line.id, actor="revisor", decision="approved")
    session.add(decision)
    await session.commit()
    return decision


class TestBrincoUniqueness:
    def test_multiple_animals_may_have_no_brinco(self) -> None:
        """142 registros da baseline não têm brinco. Todos devem caber."""

        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Sem brinco")
                    session.add_all(
                        [
                            Animal(farm_id=farm.id, identifier="sb-1", brinco=None),
                            Animal(farm_id=farm.id, identifier="sb-2", brinco=None),
                            Animal(farm_id=farm.id, identifier="sb-3", brinco=None),
                        ]
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_duplicate_brinco_in_same_farm_is_rejected(self) -> None:
        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Brinco duplicado")
                    session.add(Animal(farm_id=farm.id, identifier="a-1", brinco="B2-008"))
                    await session.commit()
                    session.add(Animal(farm_id=farm.id, identifier="a-2", brinco="B2-008"))
                    with pytest.raises(IntegrityError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_duplicate_legacy_id_is_rejected(self) -> None:
        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Legacy duplicado")
                    session.add(
                        Animal(farm_id=farm.id, identifier="l-1", legacy_id="v-malhadinha")
                    )
                    await session.commit()
                    session.add(
                        Animal(farm_id=farm.id, identifier="l-2", legacy_id="v-malhadinha")
                    )
                    with pytest.raises(IntegrityError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_duplicate_numero_legado_is_allowed(self) -> None:
        """346, 570 e '' colidem na baseline. Número não é identidade."""

        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Numero duplicado")
                    session.add_all(
                        [
                            Animal(
                                farm_id=farm.id,
                                identifier="n-1",
                                name="PONTA FINA",
                                numero_legado="346",
                            ),
                            Animal(
                                farm_id=farm.id,
                                identifier="n-2",
                                name="PONTA FINA DO ABREU",
                                numero_legado="346",
                            ),
                        ]
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())


class TestLotHistory:
    def test_animal_may_have_only_one_current_lot(self) -> None:
        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Lote vigente")
                    animal = Animal(farm_id=farm.id, identifier="lot-1")
                    session.add(animal)
                    await session.commit()
                    session.add(
                        AnimalLotAssignment(
                            animal_id=animal.id,
                            lote="LOTE 1",
                            valid_from=date(2026, 1, 1),
                            source="legacy_baseline",
                        )
                    )
                    await session.commit()
                    session.add(
                        AnimalLotAssignment(
                            animal_id=animal.id,
                            lote="LOTE 2",
                            valid_from=date(2026, 6, 1),
                            source="import",
                        )
                    )
                    with pytest.raises(IntegrityError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_closed_period_allows_a_new_current_lot(self) -> None:
        """Mudar de lote encerra a vigência anterior e abre outra."""

        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Troca de lote")
                    animal = Animal(farm_id=farm.id, identifier="lot-2")
                    session.add(animal)
                    await session.commit()
                    session.add(
                        AnimalLotAssignment(
                            animal_id=animal.id,
                            lote="LOTE 1",
                            valid_from=date(2026, 1, 1),
                            valid_to=date(2026, 5, 31),
                            source="legacy_baseline",
                        )
                    )
                    await session.commit()
                    session.add(
                        AnimalLotAssignment(
                            animal_id=animal.id,
                            lote="LOTE 2",
                            valid_from=date(2026, 6, 1),
                            source="import",
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_period_end_before_start_is_rejected(self) -> None:
        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Periodo invalido")
                    animal = Animal(farm_id=farm.id, identifier="lot-3")
                    session.add(animal)
                    await session.commit()
                    session.add(
                        AnimalLotAssignment(
                            animal_id=animal.id,
                            lote="LOTE 1",
                            valid_from=date(2026, 6, 1),
                            valid_to=date(2026, 1, 1),
                            source="manual",
                        )
                    )
                    with pytest.raises(IntegrityError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())


class TestMeasurementProvenance:
    def test_legacy_baseline_measurement_needs_no_ocr_review(self) -> None:
        """O ponto central: migrar as 152 medições sem fabricar revisão."""

        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Baseline provenance")
                    animal = Animal(farm_id=farm.id, identifier="bp-1")
                    session.add(animal)
                    await session.commit()
                    baseline = await _make_baseline_import(session, farm.id)
                    session.add(
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            values={"producao": 12.0},
                            status="active",
                            provenance="legacy_baseline",
                            baseline_import_id=baseline.id,
                            reviewed_by="titular",
                            lote_observado="LOTE 3",
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_legacy_baseline_without_baseline_import_is_rejected(self) -> None:
        """A permissividade vale só para a origem legítima da baseline."""

        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Baseline sem import")
                    animal = Animal(farm_id=farm.id, identifier="bp-2")
                    session.add(animal)
                    await session.commit()
                    session.add(
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            values={"producao": 12.0},
                            status="active",
                            provenance="legacy_baseline",
                            baseline_import_id=None,
                            reviewed_by="titular",
                        )
                    )
                    with pytest.raises(DBAPIError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_ocr_review_still_requires_review_decision(self) -> None:
        """O rigor do pipeline de ingestão não foi afrouxado."""

        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "OCR sem revisao")
                    animal = Animal(farm_id=farm.id, identifier="bp-3")
                    session.add(animal)
                    await session.commit()
                    session.add(
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            values={"producao": 12.0},
                            status="active",
                            provenance="ocr_review",
                            review_decision_id=None,
                            reviewed_by="revisor",
                        )
                    )
                    with pytest.raises(DBAPIError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_ocr_review_with_decision_is_accepted(self) -> None:
        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "OCR com revisao")
                    animal = Animal(farm_id=farm.id, identifier="bp-4")
                    session.add(animal)
                    await session.commit()
                    decision = await _make_review_decision(session, farm.id)
                    session.add(
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            values={"producao": 12.0},
                            status="active",
                            provenance="ocr_review",
                            review_decision_id=decision.id,
                            reviewed_by="revisor",
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_unknown_provenance_is_rejected(self) -> None:
        async def scenario() -> None:
            engine, factory = await _session_factory()
            try:
                async with factory() as session:
                    farm = await _make_farm(session, "Provenance invalida")
                    animal = Animal(farm_id=farm.id, identifier="bp-5")
                    session.add(animal)
                    await session.commit()
                    session.add(
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            values={"producao": 12.0},
                            status="superseded",
                            provenance="inventada",
                        )
                    )
                    with pytest.raises(DBAPIError):
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(scenario())
