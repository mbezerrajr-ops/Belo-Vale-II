"""Foto enviada pelo app → propostas na caixa de Revisão.

Reaproveita a canalização das fichas (upload, MinIO, fila do Celery, recusa
de foto repetida, reprocessar) e troca o passo do meio: o leitor devolve
eventos tipados, não linhas de ficha, e eles entram como propostas pendentes
pelo mesmo caminho do comando de carga — associação só pelo brinco, com
sugestões e alertas para quem revisa.

A leitura é o único passo que depende de GPU, e é assíncrona de propósito: se
o leitor estiver fora do ar, a leitura fica `failed`, a foto continua
guardada, e o reprocessar que já existe tenta de novo. O app segue
funcionando sem ele.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventProposalSource, ExtractionRun, MediaAsset, Import, User
from app.services.event_extraction import EventExtractor
from app.services.event_proposals import create_proposals
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)


class PhotoReadingError(Exception):
    """A foto não pôde virar proposta. A mensagem explica o que faltou."""


async def _sender(session: AsyncSession, image: MediaAsset) -> User:
    """Quem enviou a foto: a proposta é criada em nome dessa pessoa."""
    import_row = await session.get(Import, image.import_id) if image.import_id else None
    email = (import_row.initiated_by or "").strip() if import_row else ""
    user = (
        await session.scalar(
            select(User).where(func.lower(User.email) == email.lower(), User.is_active)
        )
        if email
        else None
    )
    if user is None:
        raise PhotoReadingError(
            "Não foi possível identificar quem enviou a foto; a leitura não foi feita."
        )
    return user


def _label(image: MediaAsset, import_row: Import | None) -> str:
    """Como o arquivo aparece na caixa de Revisão."""
    enviado = f"{image.created_at:%d/%m/%Y %H:%M}" if image.created_at else "sem data"
    lote = f" · {import_row.declared_lot}" if import_row and import_row.declared_lot else ""
    return f"Foto de {enviado}{lote}"


async def read_photo_into_proposals(
    session: AsyncSession,
    storage: ObjectStorage,
    reader: EventExtractor,
    *,
    extraction_run_id: UUID,
) -> ExtractionRun:
    """Lê a foto guardada e cria uma proposta por evento. Faz commit."""
    run = await session.get(ExtractionRun, extraction_run_id)
    if run is None:
        raise PhotoReadingError(f"Leitura não encontrada: {extraction_run_id}")

    image = await session.get(MediaAsset, run.media_asset_id)
    if image is None or image.object_key is None:
        raise PhotoReadingError(f"A foto da leitura {extraction_run_id} não está guardada.")

    run.status = "processing"
    run.started_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("leitura de foto iniciada extraction_run_id=%s", run.id)

    try:
        user = await _sender(session, image)
        content = storage.load(image.object_key)
        extraction = reader.extract(content, kind="photo")
    except Exception:
        await _mark_failed(session, run)
        logger.exception("leitura de foto falhou extraction_run_id=%s", run.id)
        raise

    # O que o leitor devolveu fica gravado antes de qualquer passo que possa
    # falhar depois: é a prova do que foi lido.
    run.raw_response = extraction.to_raw()
    run.model_name = extraction.extractor_version
    await session.commit()

    try:
        import_row = await session.get(Import, image.import_id) if image.import_id else None
        await create_proposals(
            session,
            farm_id=image.farm_id,
            user=user,
            kind="photo",
            label=_label(image, import_row),
            extraction=extraction,
            media_asset_id=image.id,
        )
        await session.commit()
    except Exception:
        # Descarta propostas inseridas pela metade; `raw_response` já foi
        # gravado acima e não é tocado por este rollback.
        await session.rollback()
        await _mark_failed(session, run)
        logger.exception("propostas da foto falharam extraction_run_id=%s", run.id)
        raise

    run.status = "extracted"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("leitura de foto concluída extraction_run_id=%s", run.id)
    return run


async def _mark_failed(session: AsyncSession, run: ExtractionRun) -> None:
    run.status = "failed"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
