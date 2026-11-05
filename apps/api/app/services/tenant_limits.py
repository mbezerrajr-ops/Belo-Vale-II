"""Limites compartilhados pelas fazendas de uma conta produtora."""

from datetime import UTC, datetime

from app.db.models import (
    ExtractionRun,
    Farm,
    MediaAsset,
    ProducerAccount,
    ProductionImport,
)
from fastapi import HTTPException
from sqlalchemy import func, select


async def usage(session, account_id):
    account = await session.get(ProducerAccount, account_id)
    farms = select(Farm.id).where(Farm.producer_account_id == account_id)
    size = await session.scalar(
        select(func.coalesce(func.sum(MediaAsset.byte_size), 0)).where(
            MediaAsset.farm_id.in_(farms)
        )
    )
    imported_size = await session.scalar(
        select(func.coalesce(func.sum(ProductionImport.byte_size), 0)).where(
            ProductionImport.farm_id.in_(farms)
        )
    )
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    count = await session.scalar(
        select(func.count())
        .select_from(ExtractionRun)
        .join(MediaAsset, MediaAsset.id == ExtractionRun.media_asset_id)
        .where(MediaAsset.farm_id.in_(farms), ExtractionRun.created_at >= start)
    )
    return {
        "storage_bytes": int(size or 0) + int(imported_size or 0),
        "storage_limit_bytes": account.storage_limit_bytes,
        "readings_today": int(count or 0),
        "daily_reading_limit": account.daily_reading_limit,
        "day_timezone": "UTC",
    }


async def reserve_capacity(session, farm_id, extra_bytes=0, *, reading=True):
    farm = await session.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(404, "Fazenda não encontrada.")
    if farm.producer_account_id is None:
        raise HTTPException(
            409, "Vincule a fazenda a uma conta produtora antes de enviar arquivos."
        )
    # O bloqueio dura até o commit do envio e impede uploads simultâneos de
    # ultrapassarem juntos um limite que cada um respeitaria isoladamente.
    await session.scalar(
        select(ProducerAccount)
        .where(ProducerAccount.id == farm.producer_account_id)
        .with_for_update()
    )
    current = await usage(session, farm.producer_account_id)
    if current["storage_bytes"] + extra_bytes > current["storage_limit_bytes"]:
        raise HTTPException(
            409, "O limite de armazenamento da conta produtora foi atingido."
        )
    if reading and current["readings_today"] >= current["daily_reading_limit"]:
        raise HTTPException(
            429,
            "O limite diário de leituras desta conta produtora foi atingido.",
            headers={"Retry-After": "3600"},
        )
