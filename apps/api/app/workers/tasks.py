from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from celery import Celery
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.services.media_reading import read_upload_into_proposals
from app.services.storage import get_object_storage
from app.audio.speech_reader import get_audio_reader
from app.vision.reader import get_event_reader

logger = logging.getLogger(__name__)


def _build_celery_app() -> Celery:
    # No result backend: these tasks are fire-and-forget, and "memory://" (the
    # local-dev broker fallback) is a valid kombu *broker* transport but not a
    # valid Celery *result backend* scheme.
    broker_url = get_settings().redis_url or "memory://"
    return Celery("belo_vale_ingestion", broker=broker_url)


celery_app = _build_celery_app()


@celery_app.task(name="ingestion.process_extraction_run")
def process_extraction_run(extraction_run_id: str) -> None:
    async def scenario() -> None:
        # Deliberately not the API's cached get_session_factory(): that
        # engine's asyncpg connections are tied to whatever event loop
        # first created them, but asyncio.run() gives every task a brand
        # new loop. Reusing a cached, cross-process engine here made every
        # task after the very first one fail with
        # "Future attached to a different loop" — a bug that stayed hidden
        # until the worker actually processed more than one task in its
        # lifetime. A fresh engine per task, disposed afterward, avoids the
        # cross-loop reuse entirely.
        settings = get_settings()
        engine = create_async_engine(settings.postgres_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                # A foto e a gravação viram propostas na caixa de Revisão. O
                # leitor é escolhido pelo tipo GRAVADO no envio, e só é
                # montado quando um arquivo daquele tipo chega.
                await read_upload_into_proposals(
                    session,
                    get_object_storage(),
                    {"photo": get_event_reader, "audio": get_audio_reader},
                    extraction_run_id=UUID(extraction_run_id),
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


class ExtractionDispatcher(Protocol):
    def dispatch(self, extraction_run_id: UUID) -> None: ...


class CeleryExtractionDispatcher:
    """Production dispatcher; a real broker must be reachable via REDIS_URL."""

    def dispatch(self, extraction_run_id: UUID) -> None:
        process_extraction_run.delay(str(extraction_run_id))


@lru_cache
def get_extraction_dispatcher() -> ExtractionDispatcher:
    return CeleryExtractionDispatcher()
