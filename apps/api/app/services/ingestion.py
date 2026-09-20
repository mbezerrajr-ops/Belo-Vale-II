from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtractionRun, ImageAsset, Import
from app.services.image_sniffing import sniff_image_media_type
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

_ACTIVE_RUN_STATUSES = ("pending", "processing")


class IngestionError(Exception):
    """Base for ingestion domain errors; mapped to HTTP responses in app.main."""


class InvalidImageError(IngestionError):
    pass


class ImageTooLargeError(IngestionError):
    pass


class DuplicateImageError(IngestionError):
    def __init__(self, existing_import_id: UUID) -> None:
        self.existing_import_id = existing_import_id
        super().__init__(f"duplicate image; existing import {existing_import_id}")


class ImportNotFoundError(IngestionError):
    pass


class ImportAlreadyProcessingError(IngestionError):
    pass


@dataclass(frozen=True)
class ImportStatus:
    id: UUID
    status: str
    extraction_run_id: UUID


async def create_import(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    farm_id: UUID,
    content: bytes,
    max_bytes: int,
    declared_lot: str | None = None,
    declared_measured_on: date | None = None,
    initiated_by: str | None = None,
) -> ImportStatus:
    media_type = sniff_image_media_type(content)
    if media_type is None:
        raise InvalidImageError("unsupported or unrecognized image format")
    if len(content) > max_bytes:
        raise ImageTooLargeError(f"image exceeds the maximum size of {max_bytes} bytes")

    sha256 = hashlib.sha256(content).hexdigest()

    existing = await session.scalar(
        select(ImageAsset).where(
            ImageAsset.farm_id == farm_id, ImageAsset.sha256 == sha256
        )
    )
    if existing is not None:
        logger.info(
            "duplicate image rejected farm_id=%s existing_import_id=%s",
            farm_id, existing.import_id,
        )
        raise DuplicateImageError(existing_import_id=existing.import_id)

    import_row = Import(
        farm_id=farm_id,
        status="pending",
        declared_lot=declared_lot,
        declared_measured_on=declared_measured_on,
        # Quem enviou: a proposta que sair desta foto é criada em nome dessa
        # pessoa, e o worker não tem sessão para descobrir isso depois.
        initiated_by=initiated_by,
    )
    session.add(import_row)
    await session.flush()

    object_key = f"{farm_id}/{sha256}"
    storage.save(object_key, content, media_type)

    image = ImageAsset(
        farm_id=farm_id,
        import_id=import_row.id,
        sha256=sha256,
        object_key=object_key,
        media_type=media_type,
        byte_size=len(content),
    )
    session.add(image)
    await session.flush()

    run = ExtractionRun(image_asset_id=image.id, status="pending")
    session.add(run)
    await session.flush()
    import_row.status = "queued"
    await session.commit()

    logger.info(
        "import queued import_id=%s farm_id=%s extraction_run_id=%s",
        import_row.id, farm_id, run.id,
    )
    return ImportStatus(id=import_row.id, status=import_row.status, extraction_run_id=run.id)


async def reprocess_import(session: AsyncSession, *, import_id: UUID) -> ImportStatus:
    import_row = await session.get(Import, import_id)
    if import_row is None:
        raise ImportNotFoundError(str(import_id))

    image = await session.scalar(
        select(ImageAsset).where(ImageAsset.import_id == import_id)
    )
    if image is None:
        raise ImportNotFoundError(str(import_id))

    active_run = await session.scalar(
        select(ExtractionRun).where(
            ExtractionRun.image_asset_id == image.id,
            ExtractionRun.status.in_(_ACTIVE_RUN_STATUSES),
        )
    )
    if active_run is not None:
        raise ImportAlreadyProcessingError(str(import_id))

    run = ExtractionRun(image_asset_id=image.id, status="pending")
    session.add(run)
    await session.flush()
    import_row.status = "queued"
    await session.commit()

    logger.info(
        "reprocess queued import_id=%s extraction_run_id=%s", import_row.id, run.id
    )
    return ImportStatus(id=import_row.id, status=import_row.status, extraction_run_id=run.id)
