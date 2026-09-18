"""Importação da coleta de leite por arquivo.

A pré-visualização e a gravação recebem o mesmo arquivo e recalculam tudo no
servidor: o navegador nunca manda "o que gravar", só o arquivo, a data e o
modo.

"Só leituras novas" é para qualquer conta, porque tem o mesmo efeito do
lançamento manual. "Substituir" muda leituras já registradas e fica com
revisor ou administrador, sempre com motivo.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import Farm, ProductionImport, User
from app.db.session import get_db_session
from app.routers.registry import resolve_current_farm
from app.services.production_files import (
    MAX_BYTES,
    ProductionFileError,
    parse_production_file,
)
from app.services.production_import import (
    MODE_REPLACE,
    NothingToImport,
    ProductionImportError,
    build_preview,
    commit_import,
    preview_as_dict,
)

router = APIRouter(prefix="/api/production", tags=["production-import"])

#: Papéis que podem substituir uma coleta já registrada.
_CAN_REPLACE = frozenset({"reviewer", "admin"})


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    # Lê um byte além do limite: basta para saber que passou, sem carregar
    # um arquivo gigante inteiro na memória.
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="O arquivo passa de 5 MB. Envie só a coleta do dia.",
        )
    # Só o nome, sem caminho: o nome vem do navegador e só serve para exibição.
    name = re.split(r"[\\/]", file.filename or "")[-1].strip() or "arquivo"
    return content, name[:255]


def _unprocessable(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
    )


def _import_out(record: ProductionImport, email: str, *, already: bool) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "measured_on": record.measured_on.isoformat(),
        "filename": record.filename,
        "file_format": record.file_format,
        "mode": record.mode,
        "reason": record.reason,
        "imported_by": email,
        "created_at": record.created_at.isoformat(),
        "summary": record.summary,
        "already_imported": already,
    }


@router.post("/import/preview")
async def preview_import(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    file: Annotated[UploadFile, File()],
    measured_on: Annotated[date, Form()],
) -> dict[str, Any]:
    """O que a importação faria. Não grava nada."""
    content, filename = await _read_upload(file)
    try:
        parsed = parse_production_file(content, filename)
        preview = await build_preview(
            session,
            farm_id=farm.id,
            parsed=parsed,
            content=content,
            filename=filename,
            measured_on=measured_on,
        )
    except (ProductionFileError, ProductionImportError) as error:
        raise _unprocessable(error) from error
    return preview_as_dict(preview)


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_file(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("operator"))],
    file: Annotated[UploadFile, File()],
    measured_on: Annotated[date, Form()],
    mode: Annotated[Literal["new_only", "replace"], Form()],
    reason: Annotated[str | None, Form(max_length=500)] = None,
) -> dict[str, Any]:
    if mode == MODE_REPLACE and user.role not in _CAN_REPLACE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Substituir a coleta de uma data é de revisor ou administrador.",
        )
    content, filename = await _read_upload(file)
    try:
        parsed = parse_production_file(content, filename)
        result = await commit_import(
            session,
            farm_id=farm.id,
            user=user,
            parsed=parsed,
            content=content,
            filename=filename,
            measured_on=measured_on,
            mode=mode,
            reason=reason,
        )
        if result.already_imported:
            owner = await session.get(User, result.production_import.imported_by_user_id)
            response.status_code = status.HTTP_200_OK
            return _import_out(
                result.production_import, owner.email if owner else "—", already=True
            )
        await session.commit()
    except NothingToImport as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (ProductionFileError, ProductionImportError) as error:
        await session.rollback()
        raise _unprocessable(error) from error
    except IntegrityError as error:
        # Outra importação da mesma data entrou no meio desta: o índice único
        # barrou. Nada desta foi gravado.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Outra importação desta data foi gravada ao mesmo tempo. "
                "Confira a pré-visualização e envie de novo."
            ),
        ) from error

    return _import_out(result.production_import, user.email, already=False)


@router.get("/imports")
async def list_imports(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Importações recentes, sem o arquivo: ele fica guardado para auditoria."""
    rows = await session.execute(
        select(ProductionImport, User.email)
        .join(User, User.id == ProductionImport.imported_by_user_id)
        .where(ProductionImport.farm_id == farm.id)
        .order_by(ProductionImport.created_at.desc())
        .limit(limit)
    )
    return [_import_out(record, email, already=False) for record, email in rows.all()]
