from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Animal, OfficialMeasurement


@dataclass(frozen=True)
class MeasurementRecord:
    id: UUID
    animal_id: UUID
    animal_identifier: str
    animal_name: str | None
    measured_on: date
    values: dict[str, Any]
    reviewed_by: str | None
    created_at: datetime


async def list_active_measurements(
    session: AsyncSession,
    *,
    farm_id: UUID,
    date_from: date | None,
    date_to: date | None,
) -> list[MeasurementRecord]:
    """Reads only active measurements — a superseded record must never reach
    the dashboard, per design.md's requirement that history/dashboard consume
    the active version alone."""
    query = (
        select(OfficialMeasurement, Animal)
        .join(Animal, Animal.id == OfficialMeasurement.animal_id)
        .where(Animal.farm_id == farm_id, OfficialMeasurement.status == "active")
        .order_by(OfficialMeasurement.measured_on.desc())
    )
    if date_from is not None:
        query = query.where(OfficialMeasurement.measured_on >= date_from)
    if date_to is not None:
        query = query.where(OfficialMeasurement.measured_on <= date_to)

    rows = await session.execute(query)
    return [
        MeasurementRecord(
            id=measurement.id,
            animal_id=animal.id,
            animal_identifier=animal.identifier,
            animal_name=animal.name,
            measured_on=measurement.measured_on,
            values=measurement.values,
            reviewed_by=measurement.reviewed_by,
            created_at=measurement.created_at,
        )
        for measurement, animal in rows.all()
    ]
