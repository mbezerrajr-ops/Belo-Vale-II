from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditEvent,
    ExtractedLine,
    ExtractionRun,
    ImageAsset,
    OfficialMeasurement,
    ReviewDecision,
)

Decision = Literal["approve", "reject"]


class ApprovalError(Exception):
    """Base for approval domain errors; mapped to HTTP responses in app.main."""


class LineNotFoundError(ApprovalError):
    pass


class ConcurrentReviewError(ApprovalError):
    """The caller's `expected_version` no longer matches the stored line —
    either a concurrent decision won, or this is a stale/duplicate resubmit."""


class UnmatchedAnimalError(ApprovalError):
    """Approval requires a resolved candidate animal; correct the match first."""


class MissingMeasurementDateError(ApprovalError):
    pass


class ReplacementReasonRequiredError(ApprovalError):
    """An active official measurement already exists for this animal/date;
    replacing it requires an explicit, non-empty reason."""


@dataclass(frozen=True)
class DecisionResult:
    line_id: UUID
    version: int
    measurement_id: UUID | None
    measurement_status: str | None


def _parse_measured_on(raw: Any) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)


async def _claim_line_version(
    session: AsyncSession, *, line_id: UUID, expected_version: int
) -> ExtractedLine:
    """Atomically bumps the version iff it still matches `expected_version`.

    This single conditional UPDATE is the entire concurrency control
    mechanism (see the plan's concurrency ruling for Task 6): no separate row
    lock is needed because PostgreSQL evaluates the WHERE-clause equality
    check atomically per row, so two concurrent callers starting from the
    same version can never both succeed.
    """
    result = await session.execute(
        update(ExtractedLine)
        .where(ExtractedLine.id == line_id, ExtractedLine.version == expected_version)
        .values(version=ExtractedLine.version + 1)
        .returning(ExtractedLine)
    )
    line = result.scalar_one_or_none()
    if line is not None:
        return line

    existing = await session.get(ExtractedLine, line_id)
    if existing is None:
        raise LineNotFoundError(str(line_id))
    raise ConcurrentReviewError(str(line_id))


async def decide_line(
    session: AsyncSession,
    *,
    line_id: UUID,
    reviewer_email: str,
    action: Decision,
    corrected_values: dict[str, Any] | None,
    reason: str | None,
    expected_version: int,
) -> DecisionResult:
    line = await _claim_line_version(session, line_id=line_id, expected_version=expected_version)

    merged_values = dict(line.normalized_values or {})
    if corrected_values:
        merged_values.update(corrected_values)

    review = ReviewDecision(
        extracted_line_id=line.id,
        actor=reviewer_email,
        decision="approved" if action == "approve" else "rejected",
        corrected_values=corrected_values,
        reason=reason,
        expected_version=expected_version,
    )
    session.add(review)
    await session.flush()

    measurement: OfficialMeasurement | None = None
    if action == "approve":
        if line.candidate_animal_id is None:
            raise UnmatchedAnimalError(str(line_id))

        measured_on = _parse_measured_on(merged_values.get("measured_on"))
        if measured_on is None:
            raise MissingMeasurementDateError(str(line_id))

        existing_active = await session.scalar(
            select(OfficialMeasurement).where(
                OfficialMeasurement.animal_id == line.candidate_animal_id,
                OfficialMeasurement.measured_on == measured_on,
                OfficialMeasurement.status == "active",
            )
        )
        if existing_active is not None:
            if not reason or not reason.strip():
                raise ReplacementReasonRequiredError(str(line_id))
            existing_active.status = "superseded"

        measurement = OfficialMeasurement(
            animal_id=line.candidate_animal_id,
            extracted_line_id=line.id,
            review_decision_id=review.id,
            measured_on=measured_on,
            values=merged_values,
            status="active",
            reviewed_by=reviewer_email,
        )
        session.add(measurement)

    farm_id = await session.scalar(
        select(ImageAsset.farm_id)
        .join(ExtractionRun, ExtractionRun.image_asset_id == ImageAsset.id)
        .where(ExtractionRun.id == line.extraction_run_id)
    )
    audit_action = "line_approved" if action == "approve" else "line_rejected"
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=reviewer_email,
            action=audit_action,
            entity_type="extracted_line",
            entity_id=line.id,
            previous_value=line.normalized_values,
            new_value=merged_values if action == "approve" else None,
        )
    )

    await session.commit()

    return DecisionResult(
        line_id=line.id,
        version=line.version,
        measurement_id=measurement.id if measurement else None,
        measurement_status=measurement.status if measurement else None,
    )
