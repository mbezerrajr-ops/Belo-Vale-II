"""Recusar scripts históricos monofazenda em instalações com vários clientes."""

from app.db.models import Farm
from sqlalchemy import select


async def require_legacy_single_farm(session):
    farms = list(await session.scalars(select(Farm).limit(2)))
    if len(farms) != 1:
        raise SystemExit(
            "Este script histórico exige uma cópia isolada com exatamente uma fazenda. Não o execute na plataforma de vários produtores."
        )
    return farms[0].id
