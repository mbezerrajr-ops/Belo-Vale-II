"""Arquivo enviado pelo app → propostas na caixa de Revisão.

A foto da folha e a gravação da ordenha fazem o mesmo caminho: entram pelo
mesmo envio, ficam no mesmo armazenamento, passam pela mesma fila, e aqui
viram propostas pendentes. Só o leitor muda — o de visão lê a folha, o de
fala ouve a gravação —, e quem decide qual é o TIPO GRAVADO no envio, nunca
o que o aparelho declarou.

A máquina de estados é uma só, para as duas mídias, porque é a parte que
não pode divergir: `pending → processing → extracted | failed`, a pessoa que
enviou resolvida pelo envio, e o que o leitor devolveu gravado ANTES de
qualquer passo que possa falhar depois — é a prova do que foi lido.

A leitura é assíncrona de propósito: se o modelo estiver fora do ar, a
leitura fica `failed`, o arquivo continua guardado, e o reprocessar que já
existe tenta de novo. O app segue funcionando sem ele.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.farm_clock import FARM_TZ, farm_today
from app.db.models import ExtractionRun, Import, MediaAsset, User
from app.services.event_extraction import EventExtractor
from app.services.event_proposals import create_proposals
from app.services.media_sniffing import reading_kind
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

#: Como cada mídia aparece na caixa de Revisão.
_LABELS = {"photo": "Foto", "audio": "Áudio"}


class MediaReadingError(Exception):
    """O arquivo não pôde virar proposta. A mensagem explica o que faltou."""


async def read_upload_into_proposals(
    session: AsyncSession,
    storage: ObjectStorage,
    readers: dict[str, Callable[[], EventExtractor]],
    *,
    extraction_run_id: UUID,
) -> ExtractionRun:
    """Lê o arquivo enviado com o leitor do tipo dele. Faz commit.

    `readers` leva uma fábrica por tipo (`"photo"`, `"audio"`): o leitor só é
    montado quando um arquivo daquele tipo chega, então um worker sem
    transcritor configurado continua lendo foto normalmente.
    """
    run = await session.get(ExtractionRun, extraction_run_id)
    if run is None:
        raise MediaReadingError(f"Leitura não encontrada: {extraction_run_id}")
    media = await session.get(MediaAsset, run.media_asset_id)
    if media is None or media.object_key is None:
        raise MediaReadingError(f"O arquivo da leitura {extraction_run_id} não está guardado.")
    kind = reading_kind(media.media_type)
    return await read_media_into_proposals(
        session, storage, readers[kind](), extraction_run_id=extraction_run_id, kind=kind
    )


async def read_media_into_proposals(
    session: AsyncSession,
    storage: ObjectStorage,
    reader: EventExtractor,
    *,
    extraction_run_id: UUID,
    kind: str,
) -> ExtractionRun:
    """Lê o arquivo guardado e cria uma proposta por evento. Faz commit."""
    run = await session.get(ExtractionRun, extraction_run_id)
    if run is None:
        raise MediaReadingError(f"Leitura não encontrada: {extraction_run_id}")

    media = await session.get(MediaAsset, run.media_asset_id)
    if media is None or media.object_key is None:
        raise MediaReadingError(f"O arquivo da leitura {extraction_run_id} não está guardado.")

    run.status = "processing"
    run.started_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("leitura iniciada kind=%s extraction_run_id=%s", kind, run.id)

    try:
        user = await _sender(session, media)
        content = storage.load(media.object_key)
        extraction = reader.extract(content, kind=kind)
    except Exception:
        await _mark_failed(session, run)
        logger.exception("leitura falhou kind=%s extraction_run_id=%s", kind, run.id)
        raise

    # A fala não tem cabeçalho com data: vale o dia da fazenda em que a
    # gravação foi enviada — não o dia da leitura, que pode ser um
    # reprocessamento dias depois. Quem revisa corrige o arquivo inteiro de
    # uma vez se for preciso.
    if extraction.reference_date is None and kind == "audio":
        extraction = replace(extraction, reference_date=_farm_date(media.created_at))

    # O que o leitor devolveu fica gravado antes de qualquer passo que possa
    # falhar depois: é a prova do que foi lido.
    run.raw_response = extraction.to_raw()
    run.model_name = extraction.extractor_version
    await session.commit()

    try:
        import_row = await session.get(Import, media.import_id) if media.import_id else None
        await create_proposals(
            session,
            farm_id=media.farm_id,
            user=user,
            kind=kind,
            label=_label(kind, media, import_row),
            extraction=extraction,
            media_asset_id=media.id,
        )
        await session.commit()
    except Exception:
        # Descarta propostas inseridas pela metade; `raw_response` já foi
        # gravado acima e não é tocado por este rollback.
        await session.rollback()
        await _mark_failed(session, run)
        logger.exception("propostas falharam kind=%s extraction_run_id=%s", kind, run.id)
        raise

    run.status = "extracted"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info("leitura concluída kind=%s extraction_run_id=%s", kind, run.id)
    return run


async def _sender(session: AsyncSession, media: MediaAsset) -> User:
    """Quem enviou o arquivo: a proposta é criada em nome dessa pessoa."""
    import_row = await session.get(Import, media.import_id) if media.import_id else None
    email = (import_row.initiated_by or "").strip() if import_row else ""
    user = (
        await session.scalar(
            select(User).where(func.lower(User.email) == email.lower(), User.is_active)
        )
        if email
        else None
    )
    if user is None:
        raise MediaReadingError(
            "Não foi possível identificar quem enviou o arquivo; a leitura não foi feita."
        )
    return user


def _label(kind: str, media: MediaAsset, import_row: Import | None) -> str:
    """Como o arquivo aparece na caixa de Revisão."""
    # Na hora da fazenda: é por ela que quem enviou reconhece o arquivo.
    enviado = f"{_farm_time(media.created_at):%d/%m/%Y %H:%M}" if media.created_at else "sem data"
    lote = f" · {import_row.declared_lot}" if import_row and import_row.declared_lot else ""
    return f"{_LABELS.get(kind, 'Arquivo')} de {enviado}{lote}"


def _farm_time(enviado: datetime) -> datetime:
    """O instante no fuso da fazenda. O banco guarda em UTC."""
    if enviado.tzinfo is None:
        enviado = enviado.replace(tzinfo=timezone.utc)
    return enviado.astimezone(FARM_TZ)


def _farm_date(enviado: datetime | None):
    return farm_today() if enviado is None else _farm_time(enviado).date()


async def _mark_failed(session: AsyncSession, run: ExtractionRun) -> None:
    run.status = "failed"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
