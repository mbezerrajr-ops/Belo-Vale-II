from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtractionRun, ImageAsset, Import
from app.services.image_sniffing import sniff_image_media_type
from app.services.storage import ObjectStorage

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


async def create_import(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    farm_id: UUID,
    content: bytes,
    max_bytes: int,
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
        raise DuplicateImageError(existing_import_id=existing.import_id)

    import_row = Import(farm_id=farm_id, status="pending")
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

    session.add(ExtractionRun(image_asset_id=image.id, status="pending"))
    import_row.status = "queued"
    await session.commit()

    return ImportStatus(id=import_row.id, status=import_row.status)


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

    session.add(ExtractionRun(image_asset_id=image.id, status="pending"))
    import_row.status = "queued"
    await session.commit()

    return ImportStatus(id=import_row.id, status=import_row.status)
