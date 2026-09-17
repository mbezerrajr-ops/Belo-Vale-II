import asyncio
import os
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Animal, ExtractionRun, Farm, ImageAsset, Import, ValidationAlert
from app.services.extraction_processing import persist_extracted_lines
from app.vision.contracts import VisionExtraction, VisionLine


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def test_persist_extracted_lines_matches_animal_and_flags_a_lot_mismatch() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()

                animal = Animal(
                    farm_id=farm.id,
                    identifier="v497",
                    brinco="497",
                    name="PONTA CURTA",
                )
                session.add(animal)
                ingestion = Import(farm_id=farm.id, declared_lot="2", declared_measured_on=date(2026, 7, 22))
                session.add(ingestion)
                await session.commit()

                image = ImageAsset(farm_id=farm.id, import_id=ingestion.id, sha256="c" * 64)
                session.add(image)
                await session.flush()
                run = ExtractionRun(image_asset_id=image.id, status="processing")
                session.add(run)
                await session.commit()

                extraction = VisionExtraction(
                    header_text="LOTE 1 - 22/07/2026",
                    lot="1",
                    measured_on="22/07/2026",
                    header_confidence={},
                    provider_name="fake",
                    model_name="fake-v1",
                    lines=[
                        VisionLine(
                            animal_brinco="497",
                            animal_number="497",
                            animal_name="PONTA CURTA",
                            morning="10",
                            afternoon="8",
                            total="18",
                            notes=None,
                            confidence={},
                            bounding_boxes={},
                        )
                    ],
                )

                lines = await persist_extracted_lines(
                    session,
                    farm_id=farm.id,
                    extraction_run_id=run.id,
                    extraction=extraction,
                    declared_lot=ingestion.declared_lot,
                    declared_measured_on=ingestion.declared_measured_on,
                )

                assert len(lines) == 1
                line = lines[0]
                assert line.candidate_animal_id == animal.id
                assert line.normalized_values["total"] == "18"
                assert line.confidence is not None and line.confidence < 1.0

                alerts = list(
                    await session.scalars(
                        select(ValidationAlert).where(ValidationAlert.extracted_line_id == line.id)
                    )
                )
                assert any(alert.code == "lot_mismatch" for alert in alerts)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_persist_extracted_lines_flags_unknown_animal_with_no_candidates() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()

                image = ImageAsset(farm_id=farm.id, sha256="d" * 64)
                session.add(image)
                await session.flush()
                run = ExtractionRun(image_asset_id=image.id, status="processing")
                session.add(run)
                await session.commit()

                extraction = VisionExtraction(
                    header_text=None,
                    lot="1",
                    measured_on="22/07/2026",
                    header_confidence={},
                    provider_name="fake",
                    model_name="fake-v1",
                    lines=[
                        VisionLine(
                            animal_brinco="999",
                            animal_number="999",
                            animal_name="DESCONHECIDA",
                            morning="10",
                            afternoon="8",
                            total="18",
                            notes=None,
                            confidence={},
                            bounding_boxes={},
                        )
                    ],
                )

                lines = await persist_extracted_lines(
                    session,
                    farm_id=farm.id,
                    extraction_run_id=run.id,
                    extraction=extraction,
                    declared_lot=None,
                    declared_measured_on=None,
                )

                assert lines[0].candidate_animal_id is None
                alerts = list(
                    await session.scalars(
                        select(ValidationAlert).where(ValidationAlert.extracted_line_id == lines[0].id)
                    )
                )
                assert any(alert.code == "unknown_animal" for alert in alerts)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
