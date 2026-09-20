import asyncio
import io
import os
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sqlalchemy import select

from app.core.config import Settings
from app.db.models import ExtractedLine, ExtractionRun, Farm, User, ValidationAlert
from app.services.ingestion import create_import
from app.services.storage import InMemoryObjectStorage
from app.vision.contracts import VisionExtraction
from app.services.event_extraction import FakeEventExtractor
from app.vision.provider import FakeVisionProvider
import app.workers.tasks as tasks_module
from app.workers.tasks import (
    CeleryExtractionDispatcher,
    ExtractionRunNotFoundError,
    run_extraction,
)


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

                run = await session.get(ExtractionRun, created.extraction_run_id)
                assert run.status == "pending"

                completed_run = await run_extraction(
                    session, storage, FakeVisionProvider(), extraction_run_id=run.id
                )

                assert completed_run.status == "extracted"
                assert completed_run.raw_response["provider_name"] == "fake"
                assert completed_run.raw_response["lines"][0]["morning"] == "10"
                assert completed_run.started_at is not None
                assert completed_run.completed_at is not None

                extracted = list(
                    await session.scalars(
                        select(ExtractedLine).where(
                            ExtractedLine.extraction_run_id == completed_run.id
                        )
                    )
                )
                assert len(extracted) == 1
                assert extracted[0].normalized_values["animal_number"] == "497"
                # No animal 497 is registered on this farm, so the line must be
                # flagged unknown_animal rather than silently matched.
                assert extracted[0].candidate_animal_id is None
                alerts = list(
                    await session.scalars(
                        select(ValidationAlert).where(
                            ValidationAlert.extracted_line_id == extracted[0].id
                        )
                    )
                )
                assert any(alert.code == "unknown_animal" for alert in alerts)
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


class _FailingVisionProvider:
    def extract(self, image_bytes: bytes) -> VisionExtraction:
        raise RuntimeError("vision provider unavailable")


def test_run_extraction_marks_the_run_failed_on_a_provider_error() -> None:
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

                with pytest.raises(RuntimeError, match="vision provider unavailable"):
                    await run_extraction(
                        session,
                        storage,
                        _FailingVisionProvider(),
                        extraction_run_id=created.extraction_run_id,
                    )

                run = await session.get(ExtractionRun, created.extraction_run_id)
                assert run.status == "failed"
                assert run.completed_at is not None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_process_extraction_run_succeeds_across_repeated_calls_in_one_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: process_extraction_run previously reused a
    module-cached engine/session factory across calls, but each call gets
    its own event loop via asyncio.run(). asyncpg connections are bound to
    the loop that created them, so the *second* call in the same worker
    process always failed with "Future ... attached to a different loop" —
    invisible until a worker actually processed more than one task. A fresh
    engine per call, disposed afterward, is what fixes it; this test calls
    the task function directly twice, exactly like two sequential Celery
    deliveries to the same worker."""

    storage = InMemoryObjectStorage()
    settings = Settings(environment="test", postgres_url=_database_url())
    monkeypatch.setattr(tasks_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks_module, "get_object_storage", lambda: storage)
    monkeypatch.setattr(tasks_module, "get_event_reader", lambda: FakeEventExtractor())

    async def make_pending_run() -> UUID:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                # A proposta é criada em nome de quem enviou a foto.
                sender = User(
                    email=f"envio-{uuid4().hex[:8]}@belovale",
                    password_hash="x",
                    role="operator",
                    is_active=True,
                )
                session.add(sender)
                await session.commit()
                created = await create_import(
                    session,
                    storage,
                    farm_id=farm.id,
                    content=_jpeg_bytes(),
                    max_bytes=1_000_000,
                    initiated_by=sender.email,
                )
                return created.extraction_run_id
        finally:
            await engine.dispose()

    first_run_id = asyncio.run(make_pending_run())
    second_run_id = asyncio.run(make_pending_run())

    tasks_module.process_extraction_run(str(first_run_id))
    tasks_module.process_extraction_run(str(second_run_id))

    async def check_statuses() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                first = await session.get(ExtractionRun, first_run_id)
                second = await session.get(ExtractionRun, second_run_id)
                assert first.status == "extracted"
                assert second.status == "extracted"
        finally:
            await engine.dispose()

    asyncio.run(check_statuses())


def test_celery_dispatcher_enqueues_without_a_running_worker() -> None:
    """Regression test: the Celery app previously configured `backend="memory://"`,
    a valid kombu *broker* scheme but not a valid Celery *result backend* scheme,
    so every dispatch raised ModuleNotFoundError before reaching the broker."""
    CeleryExtractionDispatcher().dispatch(uuid4())
