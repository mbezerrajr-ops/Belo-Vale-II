from __future__ import annotations

import dataclasses
from datetime import date as date_
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtractedLine, OfficialMeasurement, ValidationAlert
from app.services.animal_matching import find_animal_candidates, resolve_animal_match
from app.services.normalization import NormalizedLine, normalize_date, normalize_line
from app.services.validation import ValidationContext, validate_line
from app.vision.contracts import VisionExtraction

_HISTORY_LIMIT = 5


def _line_to_dict(line: NormalizedLine) -> dict[str, Any]:
    return {
        "animal_number": line.animal_number,
        "animal_name": line.animal_name,
        "morning": str(line.morning) if line.morning is not None else None,
        "afternoon": str(line.afternoon) if line.afternoon is not None else None,
        "total": str(line.total) if line.total is not None else None,
        "measured_on": line.measured_on.isoformat() if line.measured_on else None,
        "lot": line.lot,
        "notes": line.notes,
    }


async def _recent_history_totals(session: AsyncSession, animal_id: UUID) -> list[Decimal]:
    rows = await session.scalars(
        select(OfficialMeasurement)
        .where(OfficialMeasurement.animal_id == animal_id, OfficialMeasurement.status == "active")
        .order_by(OfficialMeasurement.measured_on.desc())
        .limit(_HISTORY_LIMIT)
    )
    totals: list[Decimal] = []
    for measurement in rows:
        raw_total = (measurement.values or {}).get("total")
        if raw_total is not None:
            totals.append(Decimal(str(raw_total)))
    return totals


async def _existing_measurement_dates(session: AsyncSession, animal_id: UUID) -> frozenset[date_]:
    rows = await session.scalars(
        select(OfficialMeasurement.measured_on).where(
            OfficialMeasurement.animal_id == animal_id, OfficialMeasurement.status == "active"
        )
    )
    return frozenset(rows)


async def persist_extracted_lines(
    session: AsyncSession,
    *,
    farm_id: UUID,
    extraction_run_id: UUID,
    extraction: VisionExtraction,
    declared_lot: str | None,
    declared_measured_on: date_ | None,
) -> list[ExtractedLine]:
    """Normalizes, matches and validates every raw vision line, then persists
    it as a reviewable ExtractedLine plus its ValidationAlert rows. This is
    the "motor de decisão" step design.md places between the vision adapter
    and human review — nothing before Task 6 ever created these rows."""
    header_measured_on = normalize_date(extraction.measured_on)

    persisted: list[ExtractedLine] = []
    for index, vision_line in enumerate(extraction.lines, start=1):
        normalized = normalize_line(
            raw_animal_number=vision_line.animal_number,
            raw_animal_name=vision_line.animal_name,
            raw_morning=vision_line.morning,
            raw_afternoon=vision_line.afternoon,
            raw_total=vision_line.total,
            raw_date=extraction.measured_on,
            raw_lot=extraction.lot,
            raw_notes=vision_line.notes,
        )

        candidates = await find_animal_candidates(
            session,
            farm_id=farm_id,
            animal_number=normalized.animal_number,
            animal_name=normalized.animal_name,
        )
        match = resolve_animal_match(candidates)

        history_totals: list[Decimal] = []
        existing_dates: frozenset[date_] = frozenset()
        if match.animal is not None:
            history_totals = await _recent_history_totals(session, match.animal.id)
            existing_dates = await _existing_measurement_dates(session, match.animal.id)

        result = validate_line(
            normalized,
            ValidationContext(
                match=match,
                history_totals=history_totals,
                existing_measurement_dates=existing_dates,
                header_lot=normalized.lot,
                header_measured_on=header_measured_on,
                declared_lot=declared_lot,
                declared_measured_on=declared_measured_on,
            ),
        )

        line = ExtractedLine(
            extraction_run_id=extraction_run_id,
            line_number=index,
            raw_values=dataclasses.asdict(vision_line),
            normalized_values=_line_to_dict(normalized),
            confidence=result.final_confidence,
            crop_coordinates=vision_line.bounding_boxes,
            candidate_animal_id=result.candidate_animal_id,
        )
        session.add(line)
        await session.flush()

        for alert in result.alerts:
            session.add(
                ValidationAlert(
                    extracted_line_id=line.id,
                    code=alert.code,
                    severity=alert.severity,
                    message=alert.message,
                    details=alert.details,
                )
            )

        persisted.append(line)

    return persisted
