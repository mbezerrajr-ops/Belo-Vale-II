import asyncio
import io
import os
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ExtractionRun, Farm, ImageAsset
from app.services.ingestion import create_import
from app.services.storage import InMemoryObjectStorage
from app.vision.provider import FakeVisionProvider
from app.workers.tasks import ExtractionRunNotFoundError, run_extraction


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (20, 10), color=(120, 80, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_run_extraction_persists_the_raw_provider_response() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()

                storage = InMemoryObjectStorage()
                created = await create_import(
                    session, storage, farm_id=farm.id, content=_jpeg_bytes(), max_bytes=1_000_000
                )

                image = await session.scalar(
                    select(ImageAsset).where(ImageAsset.import_id == created.id)
                )
                run = await session.scalar(
                    select(ExtractionRun).where(ExtractionRun.image_asset_id == image.id)
                )
                assert run.status == "pending"

                completed_run = await run_extraction(
                    session, storage, FakeVisionProvider(), extraction_run_id=run.id
                )

                assert completed_run.status == "extracted"
                assert completed_run.raw_response["provider_name"] == "fake"
                assert completed_run.raw_response["lines"][0]["morning"] == "10"
                assert completed_run.started_at is not None
                assert completed_run.completed_at is not None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_run_extraction_rejects_an_unknown_run() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                with pytest.raises(ExtractionRunNotFoundError):
                    await run_extraction(
                        session,
                        InMemoryObjectStorage(),
                        FakeVisionProvider(),
                        extraction_run_id=uuid4(),
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())
