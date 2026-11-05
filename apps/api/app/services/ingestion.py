from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtractionRun, MediaAsset, Import
from app.services.media_sniffing import sniff_media_type
from app.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

_ACTIVE_RUN_STATUSES = ("pending", "processing")

#: Uma leitura ainda "pendente" ou "processando" depois disto foi interrompida:
#: o PC reiniciou (queda de energia) ou o worker caiu, e a tarefa, que já tinha
#: saído da fila, não volta. A mais longa medida levou uns 11 minutos. Antes,
#: ela ficava assim para sempre, e o "tentar de novo" era recusado.
ABANDONED_AFTER = timedelta(hours=1)


def is_abandoned(run: ExtractionRun, now: datetime) -> bool:
    """Leitura ativa que passou do prazo, contado de quando começou (ou,
    se nem começou, de quando entrou na fila)."""
    if run.status not in _ACTIVE_RUN_STATUSES:
        return False
    since = run.started_at or run.created_at
    return since is not None and now - since > ABANDONED_AFTER


class IngestionError(Exception):
    """Base for ingestion domain errors; mapped to HTTP responses in app.main."""


class InvalidImageError(IngestionError):
    pass


class ImageTooLargeError(IngestionError):
    pass


class DuplicateImageError(IngestionError):
    def __init__(self, existing_import_id: UUID) -> None:
        self.existing_import_id = existing_import_id
        super().__init__(f"duplicate image; existing import {existing_import_id}")


class ImportNotFoundError(IngestionError):
    pass


class FarmNotFoundError(IngestionError):
    """O envio pediu uma fazenda que não é a do servidor."""


class ImportAlreadyProcessingError(IngestionError):
    pass


class ReprocessNotAllowedError(IngestionError):
    """Ler de novo um arquivo cuja leitura deu certo é decisão de revisor:
    criaria outra cópia de cada proposta na caixa."""


@dataclass(frozen=True)
class ImportStatus:
    id: UUID
    status: str
    extraction_run_id: UUID


async def create_import(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    farm_id: UUID,
    content: bytes,
    max_bytes: int,
    declared_lot: str | None = None,
    declared_measured_on: date | None = None,
    initiated_by: str | None = None,
) -> ImportStatus:
    # O tipo declarado pelo aparelho não entra nesta conta: vale o conteúdo.
    media_type = sniff_media_type(content)
    if media_type is None:
        raise InvalidImageError("unsupported or unrecognized image or audio format")
    if len(content) > max_bytes:
        raise ImageTooLargeError(f"image exceeds the maximum size of {max_bytes} bytes")

    sha256 = hashlib.sha256(content).hexdigest()

    existing = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.farm_id == farm_id, MediaAsset.sha256 == sha256
        )
    )
    if existing is not None:
        logger.info(
            "duplicate image rejected farm_id=%s existing_import_id=%s",
            farm_id, existing.import_id,
        )
        raise DuplicateImageError(existing_import_id=existing.import_id)

    from app.services.tenant_limits import reserve_capacity
    await reserve_capacity(session, farm_id, len(content))

    import_row = Import(
        farm_id=farm_id,
        status="pending",
        declared_lot=declared_lot,
        declared_measured_on=declared_measured_on,
        # Quem enviou: a proposta que sair desta foto é criada em nome dessa
        # pessoa, e o worker não tem sessão para descobrir isso depois.
        initiated_by=initiated_by,
    )
    session.add(import_row)
    await session.flush()

    object_key = f"{farm_id}/{sha256}"
    storage.save(object_key, content, media_type)

    image = MediaAsset(
        farm_id=farm_id,
        import_id=import_row.id,
        sha256=sha256,
        object_key=object_key,
        media_type=media_type,
        byte_size=len(content),
    )
    session.add(image)
    await session.flush()

    run = ExtractionRun(media_asset_id=image.id, status="pending")
    session.add(run)
    await session.flush()
    import_row.status = "queued"
    await session.commit()

    logger.info(
        "import queued import_id=%s farm_id=%s extraction_run_id=%s",
        import_row.id, farm_id, run.id,
    )
    return ImportStatus(id=import_row.id, status=import_row.status, extraction_run_id=run.id)


async def reprocess_import(
    session: AsyncSession, *, import_id: UUID, only_if_failed: bool = False
) -> ImportStatus:
    """Uma leitura nova do arquivo guardado.

    `only_if_failed`: para quem não é revisor — tentar de novo a leitura que
    falhou (transcritor fora do ar não é culpa de quem gravou) é permitido; a
    que deu certo, não.
    """
    import_row = await session.get(Import, import_id)
    if import_row is None:
        raise ImportNotFoundError(str(import_id))
    from app.services.tenant_limits import reserve_capacity
    await reserve_capacity(session, import_row.farm_id)

    image = await session.scalar(
        select(MediaAsset).where(MediaAsset.import_id == import_id)
    )
    if image is None:
        raise ImportNotFoundError(str(import_id))

    active_run = await session.scalar(
        select(ExtractionRun).where(
            ExtractionRun.media_asset_id == image.id,
            ExtractionRun.status.in_(_ACTIVE_RUN_STATUSES),
        )
    )
    if active_run is not None:
        now = datetime.now(timezone.utc)
        if not is_abandoned(active_run, now):
            raise ImportAlreadyProcessingError(str(import_id))
        # Fica registrada como falha, e a leitura nova começa.
        active_run.status = "failed"
        active_run.failure_code = "internal"
        active_run.completed_at = now
        logger.warning(
            "abandoned reading closed import_id=%s extraction_run_id=%s",
            import_id,
            active_run.id,
        )
    if only_if_failed:
        latest = await session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.media_asset_id == image.id)
            .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
            .limit(1)
        )
        if latest is None or latest.status != "failed":
            raise ReprocessNotAllowedError(str(import_id))

    run = ExtractionRun(media_asset_id=image.id, status="pending")
    session.add(run)
    await session.flush()
    import_row.status = "queued"
    await session.commit()

    logger.info(
        "reprocess queued import_id=%s extraction_run_id=%s", import_row.id, run.id
    )
    return ImportStatus(id=import_row.id, status=import_row.status, extraction_run_id=run.id)
