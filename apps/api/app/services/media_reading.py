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

A leitura que falha guarda o motivo, e quem enviou pergunta como está
(`reading_status`): gravação sem fala se resolve gravando de novo, ainda com
as vacas ali; leitor desligado, não — o arquivo está guardado.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.farm_clock import FARM_TZ, farm_today
from app.db.models import ExtractionRun, Import, MediaAsset, User
from app.services.event_extraction import (
    EventExtractor,
    ReaderUnavailableError,
    UnreadableContentError,
)
from app.services.event_proposals import create_proposals
from app.services.ingestion import is_abandoned
from app.services.media_sniffing import reading_kind
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

#: Como cada mídia aparece na caixa de Revisão.
_LABELS = {"photo": "Foto", "audio": "Áudio"}


class MediaReadingError(Exception):
    """O arquivo não pôde virar proposta. A mensagem explica o que faltou."""


class UnknownSenderError(MediaReadingError):
    """Ninguém responde pela leitura: quem enviou não existe mais, ou está
    desativado."""


def failure_code(error: BaseException) -> str:
    """O motivo guardado na leitura que falhou (ver `FAILURE_CODES`).

    Sai do tipo do erro, e os leitores de foto e de fala falam a mesma língua
    (`app.services.event_extraction`): este módulo não precisa saber qual
    leitor existe.
    """
    if isinstance(error, ReaderUnavailableError):
        return "reader_unavailable"
    if isinstance(error, UnreadableContentError):
        return "unreadable"
    if isinstance(error, UnknownSenderError):
        return "sender_unknown"
    return "internal"


@dataclass(frozen=True)
class ReadingStatus:
    """Como está a leitura de um arquivo enviado, para quem enviou."""

    import_id: UUID
    kind: str
    #: `pending`, `processing`, `extracted` ou `failed`.
    status: str
    #: Quantas propostas saíram — só quando a leitura terminou bem.
    proposals: int | None
    #: O motivo — só quando falhou.
    failure: str | None


async def reading_status(
    session: AsyncSession, *, import_id: UUID, farm_id: UUID
) -> ReadingStatus | None:
    """A leitura mais recente do arquivo, ou `None` se o envio não existe
    nesta fazenda. Depois de um "ler de novo", vale a leitura nova."""
    import_row = await session.get(Import, import_id)
    if import_row is None or import_row.farm_id != farm_id:
        return None
    media = await session.scalar(select(MediaAsset).where(MediaAsset.import_id == import_id))
    if media is None:
        return None
    run = await session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.media_asset_id == media.id)
        .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
        .limit(1)
    )
    if run is None:
        return None
    proposals = None
    if run.status == "extracted":
        events = (run.raw_response or {}).get("events")
        proposals = len(events) if isinstance(events, list) else None
    # Interrompida no meio (o PC reiniciou): para quem enviou, é uma falha que
    # dá para tentar de novo, não uma leitura que nunca termina.
    status = "failed" if is_abandoned(run, datetime.now(timezone.utc)) else run.status
    # Leitura que falhou antes de existir o motivo: sem ele, "internal".
    failure = (run.failure_code or "internal") if status == "failed" else None
    return ReadingStatus(
        import_id=import_id,
        kind=reading_kind(media.media_type),
        status=status,
        proposals=proposals,
        failure=failure,
    )


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
    except Exception as error:
        await _mark_failed(session, run, error)
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
    except Exception as error:
        # Descarta propostas inseridas pela metade; `raw_response` já foi
        # gravado acima e não é tocado por este rollback.
        await session.rollback()
        await _mark_failed(session, run, error)
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
        raise UnknownSenderError(
            "Não foi possível identificar quem enviou o arquivo; a leitura não foi feita."
        )
    from app.core.tenancy import available_farms
    from app.core.farm_clock import farm_timezone
    from app.services.lot_kind import active_lots
    farms = await available_farms(session, user)
    selected = next((farm for farm, _ in farms if farm.id == media.farm_id), None)
    if selected is None:
        raise UnknownSenderError("Quem enviou não tem mais acesso a esta fazenda.")
    farm_timezone.set(selected.timezone)
    active_lots.set(selected.lot_settings)
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
    from app.core.farm_clock import farm_timezone
    from zoneinfo import ZoneInfo
    return enviado.astimezone(ZoneInfo(farm_timezone.get()))


def _farm_date(enviado: datetime | None):
    return farm_today() if enviado is None else _farm_time(enviado).date()


async def _mark_failed(session: AsyncSession, run: ExtractionRun, error: BaseException) -> None:
    run.status = "failed"
    run.failure_code = failure_code(error)
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
