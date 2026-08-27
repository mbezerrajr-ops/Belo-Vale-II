import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import ExtractedLine, ExtractionRun, Farm, ImageAsset, Import, ValidationAlert
from app.services.ingestion import ImportNotFoundError
from app.services.review import get_import_review
from app.services.storage import InMemoryObjectStorage


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

        assert review.status == "pending"
        assert review.declared_lot == "1"
        assert review.declared_measured_on == "2026-07-22"
        assert len(review.lines) == 1
        assert review.lines[0].version == 1
        assert review.lines[0].crop_url == "memory://some/key.jpg?expires_in=900"
        assert review.lines[0].alerts[0].code == "unknown_animal"

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
