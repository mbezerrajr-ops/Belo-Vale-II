from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ExtractedLine,
    ExtractionRun,
    ImageAsset,
    Import,
    OfficialMeasurement,
    ValidationAlert,
)
from app.services.ingestion import ImportNotFoundError
from app.services.storage import ObjectStorage

_CROP_URL_TTL_SECONDS = 900


@dataclass(frozen=True)
class ReviewAlert:
    code: str
    severity: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ExistingMeasurement:
    id: UUID
    measured_on: str
    values: dict[str, Any]


@dataclass(frozen=True)
class ReviewLine:
    id: UUID
    line_number: int
    version: int
    raw_values: dict[str, Any]
    normalized_values: dict[str, Any] | None
    confidence: float | None
    candidate_animal_id: UUID | None
    crop_url: str | None
    alerts: list[ReviewAlert] = field(default_factory=list)
    existing_measurement: ExistingMeasurement | None = None


@dataclass(frozen=True)
class ImportReview:
    import_id: UUID
    status: str
    declared_lot: str | None
    declared_measured_on: str | None
    lines: list[ReviewLine]


async def get_import_review(
    session: AsyncSession, storage: ObjectStorage, *, import_id: UUID
) -> ImportReview:
    import_row = await session.get(Import, import_id)
    if import_row is None:
        raise ImportNotFoundError(str(import_id))

    lines: list[ReviewLine] = []
    image = await session.scalar(
        select(ImageAsset).where(ImageAsset.import_id == import_id)
    )
    if image is not None:
        latest_run = await session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.image_asset_id == image.id)
            .order_by(ExtractionRun.created_at.desc())
            .limit(1)
        )
        if latest_run is not None:
            extracted_lines = await session.scalars(
                select(ExtractedLine)
                .where(ExtractedLine.extraction_run_id == latest_run.id)
                .order_by(ExtractedLine.line_number)
            )
            crop_url = (
                storage.presigned_url(image.object_key, expires_seconds=_CROP_URL_TTL_SECONDS)
                if image.object_key
                else None
            )
            for line in extracted_lines:
                alerts = await session.scalars(
                    select(ValidationAlert).where(
                        ValidationAlert.extracted_line_id == line.id
                    )
                )

                existing_measurement: ExistingMeasurement | None = None
                measured_on_raw = (line.normalized_values or {}).get("measured_on")
                if line.candidate_animal_id is not None and measured_on_raw:
                    active = await session.scalar(
                        select(OfficialMeasurement).where(
                            OfficialMeasurement.animal_id == line.candidate_animal_id,
                            OfficialMeasurement.measured_on == date.fromisoformat(measured_on_raw),
                            OfficialMeasurement.status == "active",
                        )
                    )
                    if active is not None:
                        existing_measurement = ExistingMeasurement(
                            id=active.id,
                            measured_on=active.measured_on.isoformat(),
                            values=active.values,
                        )

                lines.append(
                    ReviewLine(
                        id=line.id,
                        line_number=line.line_number,
                        version=line.version,
                        raw_values=line.raw_values,
                        normalized_values=line.normalized_values,
                        confidence=line.confidence,
                        candidate_animal_id=line.candidate_animal_id,
                        crop_url=crop_url,
                        alerts=[
                            ReviewAlert(
                                code=alert.code,
                                severity=alert.severity,
                                message=alert.message,
                                details=alert.details or {},
                            )
                            for alert in alerts
                        ],
                        existing_measurement=existing_measurement,
                    )
                )

    return ImportReview(
        import_id=import_row.id,
        status=import_row.status,
        declared_lot=import_row.declared_lot,
        declared_measured_on=(
            import_row.declared_measured_on.isoformat()
            if import_row.declared_measured_on
            else None
        ),
        lines=lines,
    )
