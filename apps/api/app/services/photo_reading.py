"""Foto enviada pelo app → propostas na caixa de Revisão.

A máquina de estados mora em `media_reading`, compartilhada com a gravação
de voz: é a parte que não pode divergir entre as duas mídias. Este módulo
fica como porta de entrada da foto, com o nome que o resto do código já usa.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtractionRun
from app.services.event_extraction import EventExtractor
from app.services.media_reading import MediaReadingError, read_media_into_proposals
from app.services.storage import ObjectStorage

#: Nome antigo do erro, mantido para quem já o captura.
PhotoReadingError = MediaReadingError


async def read_photo_into_proposals(
    session: AsyncSession,
    storage: ObjectStorage,
    reader: EventExtractor,
    *,
    extraction_run_id: UUID,
) -> ExtractionRun:
    """Lê a foto guardada e cria uma proposta por evento. Faz commit."""
    return await read_media_into_proposals(
        session, storage, reader, extraction_run_id=extraction_run_id, kind="photo"
    )
