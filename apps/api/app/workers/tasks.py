from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timezone
from uuid import UUID

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ExtractionRun, ImageAsset
from app.db.session import get_session_factory
from app.services.image_preprocessing import preprocess_image
from app.services.storage import ObjectStorage, get_object_storage
from app.vision.contracts import VisionProvider
from app.vision.provider import get_vision_provider


def _build_celery_app() -> Celery:
    broker_url = get_settings().redis_url or "memory://"
    return Celery("belo_vale_ingestion", broker=broker_url, backend=broker_url)


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

    original_bytes = storage.load(image.object_key)
    preprocessed = preprocess_image(original_bytes)
    extraction = vision_provider.extract(preprocessed.content)

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
    run.status = "extracted"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return run


@celery_app.task(name="ingestion.process_extraction_run")
def process_extraction_run(extraction_run_id: str) -> None:
    async def scenario() -> None:
        async with get_session_factory()() as session:
            await run_extraction(
                session,
                get_object_storage(),
                get_vision_provider(),
                extraction_run_id=UUID(extraction_run_id),
            )

    asyncio.run(scenario())
