from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import has_minimum_role, require_minimum_role
from app.db.models import Farm, User
from app.db.session import get_db_session
from app.routers.registry import resolve_current_farm
from app.services.ingestion import (
    FarmNotFoundError,
    ImportStatus,
    create_import,
    reprocess_import,
)
from app.services.media_reading import reading_status
from app.services.normalization import normalize_date
from app.services.storage import ObjectStorage, get_object_storage
from app.workers.tasks import ExtractionDispatcher, get_extraction_dispatcher

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _response(created: ImportStatus) -> dict[str, str]:
    return {"id": str(created.id), "status": created.status}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_import(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
    dispatcher: Annotated[ExtractionDispatcher, Depends(get_extraction_dispatcher)],
    user: Annotated[User, Depends(require_minimum_role("operator"))],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    file: Annotated[UploadFile, File()],
    farm_id: Annotated[UUID | None, Form()] = None,
    declared_lot: Annotated[str | None, Form()] = None,
    declared_period: Annotated[str | None, Form()] = None,
) -> dict[str, str]:
    # A fazenda é a do servidor. O campo que o navegador manda só é aceito se
    # for ela: antes o envio confiava nele.
    if farm_id is not None and farm_id != farm.id:
        raise FarmNotFoundError(str(farm_id))
    content = await file.read()
    created = await create_import(
        session,
        storage,
        farm_id=farm.id,
        content=content,
        max_bytes=settings.max_upload_bytes,
        declared_lot=declared_lot,
        declared_measured_on=normalize_date(declared_period),
        initiated_by=user.email,
    )
    dispatcher.dispatch(created.extraction_run_id)
    return _response(created)


@router.post("/{import_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    dispatcher: Annotated[ExtractionDispatcher, Depends(get_extraction_dispatcher)],
    user: Annotated[User, Depends(require_minimum_role("operator"))],
) -> dict[str, str]:
    # Quem enviou tenta de novo a leitura que falhou; ler de novo a que deu
    # certo é de revisor.
    created = await reprocess_import(
        session, import_id=import_id, only_if_failed=not has_minimum_role(user, "reviewer")
    )
    dispatcher.dispatch(created.extraction_run_id)
    return _response(created)


@router.get("/{import_id}")
async def import_reading(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
) -> dict[str, str | int | None]:
    """Como está a leitura do que foi enviado.

    É o que a tela pergunta enquanto espera: sem isto, o aviso "as propostas
    aparecem aqui quando terminar" ficava na tela mesmo quando a leitura
    tinha falhado.
    """
    reading = await reading_status(session, import_id=import_id, farm_id=farm.id)
    if reading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Envio não encontrado.")
    return {
        "id": str(reading.import_id),
        "kind": reading.kind,
        "status": reading.status,
        "proposals": reading.proposals,
        "failure": reading.failure,
    }
