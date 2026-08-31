import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Animal,
    ExtractedLine,
    ExtractionRun,
    Farm,
    ImageAsset,
    Import,
    OfficialMeasurement,
    ReviewDecision,
    ValidationAlert,
)
from app.services.ingestion import ImportNotFoundError, create_import
from app.services.review import get_import_review
from app.services.storage import InMemoryObjectStorage
from app.vision.provider import FakeVisionProvider
from app.workers.tasks import run_extraction


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _run(coro_factory) -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                await coro_factory(session)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_get_import_review_assembles_lines_and_alerts() -> None:
    async def scenario(session: AsyncSession) -> None:
        farm = Farm(name="Fazenda Modelo")
        session.add(farm)
        await session.commit()

        ingestion = Import(
            farm_id=farm.id, declared_lot="1", declared_measured_on=date(2026, 7, 22)
        )
        session.add(ingestion)
        await session.commit()

        image = ImageAsset(
            farm_id=farm.id,
            import_id=ingestion.id,
            sha256="f" * 64,
            object_key="some/key.jpg",
        )
        session.add(image)
        await session.flush()
        run = ExtractionRun(image_asset_id=image.id, status="extracted")
        session.add(run)
        await session.commit()

        line = ExtractedLine(
            extraction_run_id=run.id,
            line_number=1,
            raw_values={"animal_number": "497"},
            normalized_values={"animal_number": "497", "total": "18"},
            confidence=0.9,
        )
        session.add(line)
        await session.flush()
        session.add(
            ValidationAlert(
                extracted_line_id=line.id,
                code="unknown_animal",
                severity="error",
                message="Nenhum animal cadastrado corresponde.",
                details={},
            )
        )
        await session.commit()

        review = await get_import_review(
            session, InMemoryObjectStorage(), import_id=ingestion.id
        )

        # The run (status="extracted") is the authoritative processing state
        # once it exists — Import.status ("pending" here) never advances past
        # queued on its own.
        assert review.status == "extracted"
        assert review.declared_lot == "1"
        assert review.declared_measured_on == "2026-07-22"
        assert len(review.lines) == 1
        assert review.lines[0].version == 1
        assert review.lines[0].crop_url == "memory://some/key.jpg?expires_in=900"
        assert review.lines[0].alerts[0].code == "unknown_animal"
        assert review.lines[0].existing_measurement is None

    _run(scenario)


def test_get_import_review_surfaces_an_existing_active_measurement() -> None:
    async def scenario(session: AsyncSession) -> None:
        farm = Farm(name="Fazenda Modelo")
        session.add(farm)
        await session.commit()

        animal = Animal(farm_id=farm.id, identifier="497", name="PONTA CURTA")
        ingestion = Import(farm_id=farm.id)
        session.add_all([animal, ingestion])
        await session.commit()

        # A separate, unrelated run/line only exists to satisfy the DB
        # constraint that an active measurement's review_decision_id must
        # point at an approved decision — it must not show up in this
        # import's own review.
        other_image = ImageAsset(farm_id=farm.id, sha256="b2" * 32)
        session.add(other_image)
        await session.flush()
        other_run = ExtractionRun(image_asset_id=other_image.id, status="extracted")
        session.add(other_run)
        await session.commit()

        prior_line = ExtractedLine(
            extraction_run_id=other_run.id, line_number=0, raw_values={}
        )
        session.add(prior_line)
        await session.flush()
        prior_review = ReviewDecision(
            extracted_line_id=prior_line.id,
            actor="reviewer@example.com",
            decision="approved",
        )
        session.add(prior_review)
        await session.flush()

        session.add(
            OfficialMeasurement(
                animal_id=animal.id,
                review_decision_id=prior_review.id,
                measured_on=date(2026, 7, 22),
                values={"total": "18"},
                status="active",
                reviewed_by="reviewer@example.com",
            )
        )
        await session.commit()

        image = ImageAsset(farm_id=farm.id, import_id=ingestion.id, sha256="a1" * 32)
        session.add(image)
        await session.flush()
        run = ExtractionRun(image_asset_id=image.id, status="extracted")
        session.add(run)
        await session.commit()

        line = ExtractedLine(
            extraction_run_id=run.id,
            line_number=1,
            raw_values={},
            normalized_values={"measured_on": "2026-07-22", "total": "25"},
            candidate_animal_id=animal.id,
        )
        session.add(line)
        await session.commit()

        review = await get_import_review(
            session, InMemoryObjectStorage(), import_id=ingestion.id
        )

        existing = review.lines[0].existing_measurement
        assert existing is not None
        assert existing.measured_on == "2026-07-22"
        assert existing.values["total"] == "18"

    _run(scenario)


def test_get_import_review_status_tracks_the_extraction_run_not_the_stale_import_status() -> None:
    """Regression test: found via a manual smoke test — Import.status only
    ever moves pending -> queued and never advances further, so a real
    upload that finished processing kept reporting "queued" forever unless
    the review reads the ExtractionRun's own status instead."""

    async def scenario(session: AsyncSession) -> None:
        farm = Farm(name="Fazenda Modelo")
        session.add(farm)
        await session.commit()

        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (20, 10), color=(120, 80, 40)).save(buffer, format="JPEG")

        storage = InMemoryObjectStorage()
        created = await create_import(
            session, storage, farm_id=farm.id, content=buffer.getvalue(), max_bytes=1_000_000
        )

        review_before = await get_import_review(session, storage, import_id=created.id)
        assert review_before.status == "pending"

        await run_extraction(
            session, storage, FakeVisionProvider(), extraction_run_id=created.extraction_run_id
        )

        review_after = await get_import_review(session, storage, import_id=created.id)
        assert review_after.status == "extracted"

    _run(scenario)


def test_get_import_review_raises_for_an_unknown_import() -> None:
    async def scenario(session: AsyncSession) -> None:
        with pytest.raises(ImportNotFoundError):
            await get_import_review(session, InMemoryObjectStorage(), import_id=uuid4())

    _run(scenario)


def test_get_import_review_returns_no_lines_before_any_extraction_run() -> None:
    async def scenario(session: AsyncSession) -> None:
        farm = Farm(name="Fazenda Modelo")
        session.add(farm)
        await session.commit()
        ingestion = Import(farm_id=farm.id)
        session.add(ingestion)
        await session.commit()

        review = await get_import_review(
            session, InMemoryObjectStorage(), import_id=ingestion.id
        )

        assert review.lines == []

    _run(scenario)
