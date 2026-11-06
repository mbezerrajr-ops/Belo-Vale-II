"""A gravação enviada pelo celular vira proposta na caixa de Revisão.

Mesmo caminho da foto: mesmo envio, mesmo armazenamento, mesma fila, mesma
máquina de estados. O que muda é o leitor — escolhido pelo tipo GRAVADO no
envio, nunca pelo que o aparelho declarou — e duas coisas que só a fala tem:

- o arquivo aparece na caixa como "Áudio de ...";
- a data de referência é o dia da fazenda em que a gravação foi enviada: a
  fala não tem cabeçalho com data, e sem data cada produção nasceria com um
  alerta de "data ausente", enchendo a caixa de ruído.
"""

from __future__ import annotations

import asyncio
import os
import struct
from datetime import timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audio.speech_reader import SpokenEventReader
from app.audio.transcriber import FAKE_SPEECH, FakeAudioTranscriber
from app.core.farm_clock import FARM_TZ
from tests.legacy_tenancy import grant_in_session
from app.db.models import EventProposal, EventProposalSource, ExtractionRun, Farm, MediaAsset, User
from app.services.event_extraction import FakeEventExtractor
from app.services.ingestion import create_import
from app.services.media_reading import read_upload_into_proposals
from app.services.storage import InMemoryObjectStorage


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _m4a() -> bytes:
    """Uma gravação mínima com faixa de som: passa pela porta de entrada."""
    hdlr = _box(b"hdlr", b"\x00" * 8 + b"soun" + b"\x00" * 12)
    moov = _box(b"moov", _box(b"trak", _box(b"mdia", hdlr)))
    # Um sufixo aleatório: o banco de teste persiste, e o mesmo conteúdo
    # cairia na proteção contra arquivo repetido.
    return _box(b"ftyp", b"M4A \x00\x00\x02\x00M4A ") + moov + uuid4().bytes


def _jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + uuid4().bytes


class _Leitores:
    """As duas fábricas de leitor, contando quem foi chamado."""

    def __init__(self) -> None:
        self.montados: list[str] = []
        self.fala = SpokenEventReader(
            FakeAudioTranscriber(), decode=lambda conteudo: conteudo, model_name="falso"
        )

    def fabricas(self) -> dict:
        def foto():
            self.montados.append("photo")
            return FakeEventExtractor()

        def audio():
            self.montados.append("audio")
            return self.fala

        return {"photo": foto, "audio": audio}


def _run(conteudo: bytes, body) -> None:
    async def outer() -> None:
        engine = create_async_engine(_database_url())
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                user = User(
                    email=f"operador-{uuid4().hex[:8]}@belovale",
                    password_hash="x",
                    role="operator",
                    is_active=True,
                )
                session.add(user)
                await session.commit()
                await grant_in_session(session, preferred_farm_id=farm.id)
                await session.commit()
                await session.refresh(farm)
                storage = InMemoryObjectStorage()
                created = await create_import(
                    session,
                    storage,
                    farm_id=farm.id,
                    content=conteudo,
                    max_bytes=1_000_000,
                    initiated_by=user.email,
                )
                await body(session, storage, created.extraction_run_id, farm)
        finally:
            await engine.dispose()

    asyncio.run(outer())


class TestTheRecordingBecomesProposals:
    def test_the_audio_reader_listens_and_the_proposals_say_audio(self) -> None:
        leitores = _Leitores()

        async def body(session, storage, run_id, farm):
            run = await read_upload_into_proposals(
                session, storage, leitores.fabricas(), extraction_run_id=run_id
            )
            assert run.status == "extracted"
            fonte = await session.scalar(
                select(EventProposalSource).where(EventProposalSource.farm_id == farm.id)
            )
            assert fonte.kind == "audio"
            assert fonte.label.startswith("Áudio de ")
            [proposta] = (
                await session.scalars(select(EventProposal).where(EventProposal.source_id == fonte.id))
            ).all()
            assert (proposta.event_type, proposta.brinco_lido) == ("production", "497")
            assert proposta.evidence["text"] == FAKE_SPEECH

        _run(_m4a(), body)
        # Só o leitor de fala foi montado: o de fotos nem chegou a existir.
        assert leitores.montados == ["audio"]

    def test_the_date_is_the_farm_day_the_recording_was_sent(self) -> None:
        async def body(session, storage, run_id, farm):
            await read_upload_into_proposals(
                session, storage, _Leitores().fabricas(), extraction_run_id=run_id
            )
            run = await session.get(ExtractionRun, run_id)
            midia = await session.get(MediaAsset, run.media_asset_id)
            enviado = midia.created_at
            if enviado.tzinfo is None:
                enviado = enviado.replace(tzinfo=timezone.utc)
            fonte = await session.scalar(
                select(EventProposalSource).where(EventProposalSource.farm_id == farm.id)
            )
            assert fonte.reference_date == enviado.astimezone(FARM_TZ).date()

        _run(_m4a(), body)

    def test_the_label_shows_the_farm_time(self) -> None:
        """Na prova real, uma gravação enviada às 17:16 da fazenda apareceu
        como "Áudio de ... 20:16": a hora saía em UTC. Quem revisa reconhece o
        arquivo pela hora em que mandou."""

        async def body(session, storage, run_id, farm):
            await read_upload_into_proposals(
                session, storage, _Leitores().fabricas(), extraction_run_id=run_id
            )
            run = await session.get(ExtractionRun, run_id)
            midia = await session.get(MediaAsset, run.media_asset_id)
            enviado = midia.created_at
            if enviado.tzinfo is None:
                enviado = enviado.replace(tzinfo=timezone.utc)
            fonte = await session.scalar(
                select(EventProposalSource).where(EventProposalSource.farm_id == farm.id)
            )
            assert fonte.label == f"Áudio de {enviado.astimezone(FARM_TZ):%d/%m/%Y %H:%M}"

        _run(_m4a(), body)

    def test_the_file_is_linked_to_the_source(self) -> None:
        """Quem revisa ouve a gravação ao lado do que foi entendido."""

        async def body(session, storage, run_id, farm):
            await read_upload_into_proposals(
                session, storage, _Leitores().fabricas(), extraction_run_id=run_id
            )
            run = await session.get(ExtractionRun, run_id)
            fonte = await session.scalar(
                select(EventProposalSource).where(EventProposalSource.farm_id == farm.id)
            )
            assert fonte.media_asset_id == run.media_asset_id

        _run(_m4a(), body)


class TestThePhotoStillGoesToThePhotoReader:
    def test_a_photo_is_read_by_the_photo_reader(self) -> None:
        leitores = _Leitores()

        async def body(session, storage, run_id, farm):
            await read_upload_into_proposals(
                session, storage, leitores.fabricas(), extraction_run_id=run_id
            )
            fonte = await session.scalar(
                select(EventProposalSource).where(EventProposalSource.farm_id == farm.id)
            )
            assert fonte.kind == "photo"
            assert fonte.label.startswith("Foto de ")

        _run(_jpeg(), body)
        assert leitores.montados == ["photo"]
