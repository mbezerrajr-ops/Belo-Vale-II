from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import require_minimum_role
from app.db.models import User
from app.db.session import get_db_session
from app.services.ingestion import ImportStatus, create_import, reprocess_import
from app.services.storage import ObjectStorage, get_object_storage

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _response(created: ImportStatus) -> dict[str, str]:
    return {"id": str(created.id), "status": created.status}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_import(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    farm_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, str]:
    content = await file.read()
    created = await create_import(
        session,
        storage,
        farm_id=farm_id,
        content=content,
        max_bytes=settings.max_upload_bytes,
    )
    return _response(created)


@router.post("/{import_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> dict[str, str]:
    created = await reprocess_import(session, import_id=import_id)
    return _response(created)
