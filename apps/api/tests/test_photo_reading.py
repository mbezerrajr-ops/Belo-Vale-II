"""A foto enviada pelo celular vira proposta na caixa de Revisão.

Reaproveita a canalização que já existia para as fichas (upload, MinIO, fila,
recusa de foto repetida) e troca o passo do meio: em vez de linhas de ficha,
o leitor devolve eventos, e eles entram como propostas pendentes — o mesmo
caminho do comando de carga, com as mesmas regras de associação por brinco.

O que não pode falhar:
- leitor fora do ar deixa a leitura como `failed`, sem proposta pela metade,
  e o reprocessar existente recupera;
- a proposta sabe de qual foto veio, para quem revisa conferir sem sair da tela;
- ninguém lê foto em nome de um usuário que não existe.
"""

from __future__ import annotations

import asyncio
import io
import os
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.legacy_tenancy import grant_in_session
from app.db.models import (
    Animal,
    EventProposal,
    EventProposalSource,
    ExtractionRun,
    Farm,
    User,
)
from app.services.event_extraction import (
    EventExtraction,
    ExtractedEvent,
    FakeEventExtractor,
)
from app.services.ingestion import create_import
from app.services.photo_reading import PhotoReadingError, read_photo_into_proposals
from app.services.storage import InMemoryObjectStorage
from app.vision.sheet_reader import ReaderUnavailable


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (20, 10), color=(120, 80, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


class _Reader:
    """Leitor de mentira: devolve o que mandarem, ou levanta o que mandarem."""

    def __init__(self, answer):
        self.answer = answer
        self.kinds: list[str] = []

    def extract(self, content: bytes, *, kind: str) -> EventExtraction:
        self.kinds.append(kind)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _extraction(*brincos: str) -> EventExtraction:
    return EventExtraction(
        events=[
            ExtractedEvent(
                event_type="production",
                brinco=brinco,
                nome=None,
                fields={"producao": "20"},
                evidence={"text": f"{brinco} 20"},
                confidence={"brinco": 0.9},
            )
            for brinco in brincos
        ],
        extractor_name="teste",
        extractor_version="1",
        reference_date=None,
    )


def _run(body) -> None:
    """Monta fazenda, remetente e foto enviada; entrega tudo ao corpo do teste."""

    async def outer() -> None:
        engine = create_async_engine(_database_url())
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                user = User(
                    # O banco de teste persiste entre testes: e-mail único
                    # por execução evita colisão com a rodada anterior.
                    email=f"operador-{uuid4().hex[:8]}@belovale",
                    password_hash="x",
                    role="operator",
                    is_active=True,
                )
                session.add(user)
                await session.commit()
                await grant_in_session(session)
                await session.commit()
                await session.refresh(farm)

                storage = InMemoryObjectStorage()
                created = await create_import(
                    session,
                    storage,
                    farm_id=farm.id,
                    content=_jpeg(),
                    max_bytes=1_000_000,
                    initiated_by=user.email,
                )
                await body(session, storage, farm, user, created)
        finally:
            await engine.dispose()

    asyncio.run(outer())


def test_the_photo_becomes_pending_proposals() -> None:
    async def body(session, storage, farm, user, created):
        session.add(Animal(farm_id=farm.id, identifier="389", brinco="389", name="ÁGATA"))
        await session.commit()

        run = await read_photo_into_proposals(
            session,
            storage,
            _Reader(_extraction("389")),
            extraction_run_id=created.extraction_run_id,
        )

        assert run.status == "extracted"
        assert run.started_at is not None and run.completed_at is not None

        source = (await session.scalars(select(EventProposalSource).where(EventProposalSource.farm_id == farm.id))).one()
        assert source.kind == "photo"
        assert source.created_by_user_id == user.id
        # A proposta sabe de que foto veio.
        assert source.media_asset_id is not None

        proposal = (await session.scalars(select(EventProposal).where(EventProposal.farm_id == farm.id))).one()
        assert proposal.status == "pending"
        assert proposal.brinco_lido == "389"

    _run(body)


def test_the_reader_is_told_it_is_a_photo() -> None:
    async def body(session, storage, farm, user, created):
        reader = _Reader(_extraction("389"))

        await read_photo_into_proposals(
            session, storage, reader, extraction_run_id=created.extraction_run_id
        )

        assert reader.kinds == ["photo"]

    _run(body)


def test_a_reader_that_is_down_leaves_the_reading_failed() -> None:
    """Sem leitor, nada de proposta pela metade: a foto fica guardada e o
    reprocessar existente tenta de novo."""

    async def body(session, storage, farm, user, created):
        with pytest.raises(ReaderUnavailable):
            await read_photo_into_proposals(
                session,
                storage,
                _Reader(ReaderUnavailable("leitor desligado")),
                extraction_run_id=created.extraction_run_id,
            )

        run = await session.get(ExtractionRun, created.extraction_run_id)
        assert run.status == "failed"
        assert run.completed_at is not None
        assert list(await session.scalars(select(EventProposalSource).where(EventProposalSource.farm_id == farm.id))) == []

    _run(body)


def test_an_unknown_brinco_still_becomes_a_proposal_with_an_alert() -> None:
    """Brinco que não existe no rebanho não é erro: vira proposta com alerta,
    para quem revisa escolher a vaca."""

    async def body(session, storage, farm, user, created):
        run = await read_photo_into_proposals(
            session,
            storage,
            _Reader(_extraction("999")),
            extraction_run_id=created.extraction_run_id,
        )

        assert run.status == "extracted"
        proposal = (await session.scalars(select(EventProposal).where(EventProposal.farm_id == farm.id))).one()
        assert proposal.candidate_animal_id is None
        assert any(alert["code"] == "animal_not_found" for alert in proposal.alerts)

    _run(body)


def test_a_photo_without_a_known_sender_is_refused() -> None:
    """A proposta é criada em nome de quem enviou a foto. Sem esse vínculo,
    ninguém responde pela leitura — e a leitura não acontece."""

    async def body(session, storage, farm, user, created):
        await session.delete(user)
        await session.commit()

        with pytest.raises(PhotoReadingError, match="quem enviou"):
            await read_photo_into_proposals(
                session,
                storage,
                _Reader(_extraction("389")),
                extraction_run_id=created.extraction_run_id,
            )

        run = await session.get(ExtractionRun, created.extraction_run_id)
        assert run.status == "failed"

    _run(body)


def test_the_fake_reader_goes_through_the_same_path() -> None:
    """É o leitor que o CI usa: o caminho inteiro precisa funcionar sem GPU."""

    async def body(session, storage, farm, user, created):
        session.add(
            Animal(farm_id=farm.id, identifier="497", brinco="497", name="PONTA CURTA")
        )
        await session.commit()

        run = await read_photo_into_proposals(
            session,
            storage,
            FakeEventExtractor(),
            extraction_run_id=created.extraction_run_id,
        )

        assert run.status == "extracted"
        proposals = list(await session.scalars(select(EventProposal).where(EventProposal.farm_id == farm.id)))
        assert [p.brinco_lido for p in proposals] == ["497", "497"]

    _run(body)
