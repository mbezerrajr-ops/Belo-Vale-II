"""Funcionalidades disponíveis nesta instalação.

A interface pergunta aqui o que mostrar, em vez de supor. Hoje só a leitura de
fichas por foto varia: ela depende de um provedor de OCR real.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings, photo_sheets_enabled
from app.core.security import require_minimum_role
from app.db.models import User

router = APIRouter(prefix="/api", tags=["features"])


@router.get("/features")
async def features(
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
) -> dict[str, bool]:
    return {"photo_sheets": photo_sheets_enabled(settings)}
