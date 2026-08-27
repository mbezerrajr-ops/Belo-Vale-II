from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import User
from app.db.session import get_db_session
from app.services.measurements import list_active_measurements

router = APIRouter(tags=["measurements"])


@router.get("/api/measurements")
async def get_measurements(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    farm_id: UUID,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[dict[str, Any]]:
    records = await list_active_measurements(
        session, farm_id=farm_id, date_from=date_from, date_to=date_to
    )
    return [
        {
            "id": str(record.id),
            "animal_id": str(record.animal_id),
            "animal_identifier": record.animal_identifier,
            "animal_name": record.animal_name,
            "measured_on": record.measured_on.isoformat(),
            "values": record.values,
            "reviewed_by": record.reviewed_by,
            "created_at": record.created_at.isoformat(),
        }
        for record in records
    ]
