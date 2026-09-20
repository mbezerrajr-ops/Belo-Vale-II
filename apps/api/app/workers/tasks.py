from __future__ import annotations

import asyncio
import dataclasses
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import ExtractionRun, Import, ImageAsset
from app.services.extraction_processing import persist_extracted_lines
from app.services.photo_reading import read_photo_into_proposals
from app.services.image_preprocessing import preprocess_image
from app.services.storage import ObjectStorage, get_object_storage
from app.vision.contracts import VisionProvider
from app.vision.provider import get_vision_provider
from app.vision.reader import get_event_reader

logger = logging.getLogger(__name__)


def _build_celery_app() -> Celery:
    # No result backend: these tasks are fire-and-forget, and "memory://" (the
    # local-dev broker fallback) is a valid kombu *broker* transport but not a
    # valid Celery *result backend* scheme.
    broker_url = get_settings().redis_url or "memory://"
    return Celery("belo_vale_ingestion", broker=broker_url)


celery_app = _build_celery_app()


class ExtractionRunNotFoundError(Exception):
    pass


class ImageObjectMissingError(Exception):
    pass


async def run_extraction(
    session: AsyncSession,
    storage: ObjectStorage,
    vision_provider: VisionProvider,
    *,
    extraction_run_id: UUID,
) -> ExtractionRun:
    """Preprocess the stored photo, run it through the vision adapter, and
    persist the raw response. Never invents rows in extracted_lines — that
    normalization step belongs to Task 5, which reads run.raw_response."""

    run = await session.get(ExtractionRun, extraction_run_id)
    if run is None:
        raise ExtractionRunNotFoundError(str(extraction_run_id))

    image = await session.get(ImageAsset, run.image_asset_id)
    if image is None or image.object_key is None:
        raise ImageObjectMissingError(str(extraction_run_id))

    run.status = "processing"
    run.started_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("extraction processing extraction_run_id=%s", run.id)

    try:
        original_bytes = storage.load(image.object_key)
        preprocessed = preprocess_image(original_bytes)
        extraction = vision_provider.extract(preprocessed.content)
    except Exception:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.exception("extraction failed extraction_run_id=%s", run.id)
        raise

    # Raw provider output is committed on its own so it survives even if the
    # normalization/validation step below fails partway through.
    run.raw_response = {
        "header_text": extraction.header_text,
        "lot": extraction.lot,
        "measured_on": extraction.measured_on,
        "header_confidence": extraction.header_confidence,
        "provider_name": extraction.provider_name,
        "model_name": extraction.model_name,
        "lines": [dataclasses.asdict(line) for line in extraction.lines],
    }
    run.model_name = extraction.model_name
    await session.commit()

    try:
        import_row = (
            await session.get(Import, image.import_id) if image.import_id else None
        )
        await persist_extracted_lines(
            session,
            farm_id=image.farm_id,
            extraction_run_id=run.id,
            extraction=extraction,
            declared_lot=import_row.declared_lot if import_row else None,
            declared_measured_on=import_row.declared_measured_on if import_row else None,
        )
    except Exception:
        # Discard any partially-inserted lines/alerts; raw_response above was
        # already committed and is untouched by this rollback.
        await session.rollback()
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.exception("validation failed extraction_run_id=%s", run.id)
        raise

    run.status = "extracted"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("extraction extracted extraction_run_id=%s", run.id)
    return run


@celery_app.task(name="ingestion.process_extraction_run")
def process_extraction_run(extraction_run_id: str) -> None:
    async def scenario() -> None:
        # Deliberately not the API's cached get_session_factory(): that
        # engine's asyncpg connections are tied to whatever event loop
        # first created them, but asyncio.run() gives every task a brand
        # new loop. Reusing a cached, cross-process engine here made every
        # task after the very first one fail with
        # "Future attached to a different loop" — a bug that stayed hidden
        # until the worker actually processed more than one task in its
        # lifetime. A fresh engine per task, disposed afterward, avoids the
        # cross-loop reuse entirely.
        settings = get_settings()
        engine = create_async_engine(settings.postgres_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                # Caminho oficial: a foto vira propostas na caixa de Revisão.
                # `run_extraction` (linhas de ficha, provenance ocr_review)
                # continua no módulo para as fichas antigas já no banco.
                await read_photo_into_proposals(
                    session,
                    get_object_storage(),
                    get_event_reader(),
                    extraction_run_id=UUID(extraction_run_id),
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


class ExtractionDispatcher(Protocol):
    def dispatch(self, extraction_run_id: UUID) -> None: ...


class CeleryExtractionDispatcher:
    """Production dispatcher; a real broker must be reachable via REDIS_URL."""

    def dispatch(self, extraction_run_id: UUID) -> None:
        process_extraction_run.delay(str(extraction_run_id))


@lru_cache
def get_extraction_dispatcher() -> ExtractionDispatcher:
    return CeleryExtractionDispatcher()
