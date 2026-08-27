from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.reviews import DecisionRequest
from app.services.approval import DecisionResult, decide_line
from app.services.review import ImportReview, get_import_review
from app.services.storage import ObjectStorage, get_object_storage

router = APIRouter(tags=["reviews"])


def _review_response(review: ImportReview) -> dict[str, Any]:
    return {
        "import_id": str(review.import_id),
        "status": review.status,
        "declared_lot": review.declared_lot,
        "declared_measured_on": review.declared_measured_on,
        "lines": [
            {
                "id": str(line.id),
                "line_number": line.line_number,
                "version": line.version,
                "raw_values": line.raw_values,
                "normalized_values": line.normalized_values,
                "confidence": line.confidence,
                "candidate_animal_id": (
                    str(line.candidate_animal_id) if line.candidate_animal_id else None
                ),
                "crop_url": line.crop_url,
                "alerts": [
                    {
                        "code": alert.code,
                        "severity": alert.severity,
                        "message": alert.message,
                        "details": alert.details,
                    }
                    for alert in line.alerts
                ],
                "existing_measurement": (
                    {
                        "id": str(line.existing_measurement.id),
                        "measured_on": line.existing_measurement.measured_on,
                        "values": line.existing_measurement.values,
                    }
                    if line.existing_measurement
                    else None
                ),
            }
            for line in review.lines
        ],
    }


def _decision_response(result: DecisionResult) -> dict[str, Any]:
    return {
        "line_id": str(result.line_id),
        "version": result.version,
        "measurement_id": str(result.measurement_id) if result.measurement_id else None,
        "measurement_status": result.measurement_status,
    }


@router.get("/api/imports/{import_id}/review")
async def get_review(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
) -> dict[str, Any]:
    review = await get_import_review(session, storage, import_id=import_id)
    return _review_response(review)


@router.post("/api/extracted-lines/{line_id}/decision")
async def decide(
    line_id: UUID,
    payload: DecisionRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> dict[str, Any]:
    result = await decide_line(
        session,
        line_id=line_id,
        reviewer_email=user.email,
        action=payload.action,
        corrected_values=payload.corrected_values,
        reason=payload.reason,
        expected_version=payload.expected_version,
    )
    return _decision_response(result)
