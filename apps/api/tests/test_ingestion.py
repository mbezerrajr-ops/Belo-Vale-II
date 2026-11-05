import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.core.security import get_current_user
from app.core.tenancy import get_farm_access, FarmAccess
from fastapi import Depends
from tests.legacy_tenancy import grant_in_session
from app.db.models import ExtractionRun, Farm, MediaAsset, User
from app.routers.registry import resolve_current_farm
from app.db.session import get_db_session
from app.main import create_app
from app.services.media_sniffing import sniff_image_media_type
from app.services.ingestion import (
    DuplicateImageError,
    ImageTooLargeError,
    ImportAlreadyProcessingError,
    InvalidImageError,
    create_import,
    reprocess_import,
)
from app.services.storage import InMemoryObjectStorage, get_object_storage
from app.workers.tasks import get_extraction_dispatcher

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_AUTH_SECRET = "test-only-secret-with-at-least-32-bytes"


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def test_sniffer_identifies_jpeg_and_png_and_rejects_unknown_bytes() -> None:
    assert sniff_image_media_type(_JPEG_BYTES) == "image/jpeg"
    assert sniff_image_media_type(_PNG_BYTES) == "image/png"
    assert sniff_image_media_type(b"not an image") is None


def test_create_import_persists_farm_and_image_and_stores_bytes() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()
                await grant_in_session(session)
                await session.commit()
                await session.refresh(farm)

                storage = InMemoryObjectStorage()
                created = await create_import(
                    session, storage, farm_id=farm.id, content=_JPEG_BYTES, max_bytes=1_000_000
                )

                assert created.status == "queued"
                object_key = f"{farm.id}/{hashlib.sha256(_JPEG_BYTES).hexdigest()}"
                assert storage.objects[object_key] == _JPEG_BYTES
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_create_import_rejects_a_duplicate_image_for_the_same_farm() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()
                await grant_in_session(session)
                await session.commit()
                await session.refresh(farm)
                storage = InMemoryObjectStorage()

                first = await create_import(
                    session, storage, farm_id=farm.id, content=_JPEG_BYTES, max_bytes=1_000_000
                )

                with pytest.raises(DuplicateImageError) as error:
                    await create_import(
                        session, storage, farm_id=farm.id, content=_JPEG_BYTES, max_bytes=1_000_000
                    )
                assert error.value.existing_import_id == first.id
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_create_import_rejects_unrecognized_image_bytes() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()
                await grant_in_session(session)
                await session.commit()
                await session.refresh(farm)

                with pytest.raises(InvalidImageError):
                    await create_import(
                        session,
                        InMemoryObjectStorage(),
                        farm_id=farm.id,
                        content=b"not an image",
                        max_bytes=1_000_000,
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_create_import_rejects_an_image_larger_than_the_configured_limit() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()
                await grant_in_session(session)
                await session.commit()
                await session.refresh(farm)

                with pytest.raises(ImageTooLargeError):
                    await create_import(
                        session,
                        InMemoryObjectStorage(),
                        farm_id=farm.id,
                        content=_JPEG_BYTES,
                        max_bytes=4,
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_reprocess_enqueues_a_new_run_for_an_existing_import() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()
                await grant_in_session(session)
                await session.commit()
                await session.refresh(farm)

                created = await create_import(
                    session,
                    InMemoryObjectStorage(),
                    farm_id=farm.id,
                    content=_JPEG_BYTES,
                    max_bytes=1_000_000,
                )

                # Upload already queued a pending run; reprocessing while it is
                # still in flight must not queue a second, competing run.
                with pytest.raises(ImportAlreadyProcessingError):
                    await reprocess_import(session, import_id=created.id)

                pending_run = await session.scalar(
                    select(ExtractionRun).where(ExtractionRun.media_asset_id.in_(
                        select(MediaAsset.id).where(MediaAsset.import_id == created.id)
                    ))
                )
                pending_run.status = "extracted"
                await session.commit()

                reprocessed = await reprocess_import(session, import_id=created.id)
                assert reprocessed.id == created.id
                assert reprocessed.status == "queued"

                with pytest.raises(ImportAlreadyProcessingError):
                    await reprocess_import(session, import_id=created.id)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


class _RecordingSession:
    """Minimal AsyncSession-shaped stub for HTTP-contract tests only.

    `.scalar()` answers the configured user only for a `select(User)` query
    (what `get_current_user` issues) and `None` for every other entity, so it
    never masquerades as an unrelated row (e.g. the ingestion duplicate check).
    """

    def __init__(self, *, user: User | None = None) -> None:
        self.added: list[Any] = []
        self._user = user

    async def scalar(self, statement: object) -> Any:
        descriptions = getattr(statement, "column_descriptions", None)
        if descriptions and descriptions[0].get("type") is User:
            return self._user
        return None

    async def get(self, model: object, identifier: object) -> None:
        from app.db.models import ProducerAccount
        if model is Farm: return _FARM
        if model is ProducerAccount: return ProducerAccount(id=_FARM.producer_account_id, name="Teste", storage_limit_bytes=1_000_000_000, daily_reading_limit=100)
        return None

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeExtractionDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[Any] = []

    def dispatch(self, extraction_run_id: Any) -> None:
        self.dispatched.append(extraction_run_id)


def _build_client(
    *, user: User | None = None
) -> tuple[TestClient, "_FakeExtractionDispatcher"]:
    session = _RecordingSession(user=user)
    settings = Settings(environment="test", auth_secret=_AUTH_SECRET, auth_token_ttl_seconds=900)
    dispatcher = _FakeExtractionDispatcher()

    async def override_session() -> AsyncIterator[_RecordingSession]:
        yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: InMemoryObjectStorage()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_extraction_dispatcher] = lambda: dispatcher
    # A fazenda vem do servidor; aqui, uma fixa, sem banco.
    app.dependency_overrides[resolve_current_farm] = lambda: _FARM
    async def access(user=Depends(get_current_user)):
        return FarmAccess(_FARM, user, user.role)
    app.dependency_overrides[get_farm_access] = access
    return TestClient(app), dispatcher


_FARM = Farm(id=uuid4(), name="Fazenda Modelo", producer_account_id=uuid4(), timezone="America/Recife", lot_settings=[])


def _operator() -> User:
    return User(
        id=uuid4(),
        email="operator@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="operator",
        is_active=True,
    )


def test_upload_requires_authentication() -> None:
    client, dispatcher = _build_client()

    response = client.post(
        "/api/imports",
        data={"farm_id": str(uuid4())},
        files={"file": ("sheet.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    assert response.status_code == 401
    assert dispatcher.dispatched == []


def test_upload_creates_a_queued_import_and_dispatches_extraction() -> None:
    user = _operator()
    client, dispatcher = _build_client(user=user)
    token = create_access_token(user.id, _AUTH_SECRET, 900)

    response = client.post(
        "/api/imports",
        data={"farm_id": str(_FARM.id)},
        files={"file": ("sheet.jpg", _JPEG_BYTES, "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert len(dispatcher.dispatched) == 1


def test_reprocess_requires_authentication() -> None:
    client, dispatcher = _build_client()

    response = client.post(f"/api/imports/{uuid4()}/reprocess")

    assert response.status_code == 401
    assert dispatcher.dispatched == []


def test_authenticated_reviewer_receives_404_for_an_unknown_import() -> None:
    user = User(
        id=uuid4(),
        email="reviewer@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="reviewer",
        is_active=True,
    )
    client, dispatcher = _build_client(user=user)
    token = create_access_token(user.id, _AUTH_SECRET, 900)

    response = client.post(
        f"/api/imports/{uuid4()}/reprocess",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "import_not_found"
    assert dispatcher.dispatched == []
