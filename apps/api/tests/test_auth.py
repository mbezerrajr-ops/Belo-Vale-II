import base64
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.core.bootstrap_admin import create_first_admin
from app.core.config import Settings, get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    require_minimum_role,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db_session
from app.main import create_app


class StubSession:
    def __init__(self, user: User) -> None:
        self.user = user

    async def scalar(self, statement: object) -> User | None:
        return self.user


class EmptyCapturingSession:
    def __init__(self) -> None:
        self.added: User | None = None
        self.committed = False

    async def scalar(self, statement: object) -> None:
        return None

    def add(self, user: User) -> None:
        self.added = user

    async def commit(self) -> None:
        self.committed = True


def _client_for(role: str = "operator") -> tuple[TestClient, User]:
    user = User(
        id=uuid4(),
        email="reviewer@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
        is_active=True,
    )
    app = create_app()
    settings = Settings(
        environment="test",
        auth_secret="test-only-secret-with-at-least-32-bytes",
        auth_token_ttl_seconds=900,
    )

    async def override_session() -> AsyncIterator[StubSession]:
        yield StubSession(user)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db_session] = override_session

    @app.get("/test/reviewer")
    async def reviewer_only(
        current_user: User = Depends(require_minimum_role("reviewer")),
    ) -> dict[str, str]:
        return {"user_id": str(current_user.id)}

    return TestClient(app), user


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "email": "reviewer@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert "password" not in body
    return body["access_token"]


def test_password_is_hashed_before_it_can_be_persisted() -> None:
    plain_password = "correct horse battery staple"

    encoded = hash_password(plain_password)

    assert plain_password not in encoded
    assert encoded.startswith("scrypt$")
    assert verify_password(plain_password, encoded)
    assert not verify_password("wrong password", encoded)
    assert "password" not in User.__table__.columns
    assert "password_hash" in User.__table__.columns


def test_request_without_credentials_receives_401() -> None:
    client, _ = _client_for(role="reviewer")

    response = client.get("/test/reviewer")

    assert response.status_code == 401


def test_insufficient_role_receives_403() -> None:
    client, _ = _client_for(role="operator")
    token = _login(client)

    response = client.get(
        "/test/reviewer", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403


def test_permitted_role_is_accepted() -> None:
    client, user = _client_for(role="reviewer")
    token = _login(client)

    response = client.get(
        "/test/reviewer", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.id)}


def test_login_rejects_an_invalid_password_without_returning_a_token() -> None:
    client, _ = _client_for(role="reviewer")

    response = client.post(
        "/api/auth/login",
        json={"email": "reviewer@example.com", "password": "wrong password"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_access_token_is_rejected_after_its_expiration() -> None:
    issued_at = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    secret = "test-only-secret-with-at-least-32-bytes"
    user_id = uuid4()
    token = create_access_token(user_id, secret, 60, now=issued_at)

    try:
        decode_access_token(token, secret, now=issued_at + timedelta(seconds=61))
    except ValueError as error:
        assert str(error) == "invalid or expired access token"
    else:
        raise AssertionError("expired access token was accepted")


def test_request_rejects_a_token_with_a_tampered_payload() -> None:
    client, _ = _client_for(role="reviewer")
    token = _login(client)
    header, _, signature = token.split(".")
    tampered_payload = base64.urlsafe_b64encode(
        b'{"sub":"00000000-0000-0000-0000-000000000000","iat":0,"exp":4102444800}'
    ).rstrip(b"=").decode("ascii")

    response = client.get(
        "/test/reviewer",
        headers={"Authorization": f"Bearer {header}.{tampered_payload}.{signature}"},
    )

    assert response.status_code == 401


def test_request_rejects_a_token_with_a_tampered_signature() -> None:
    client, _ = _client_for(role="reviewer")
    token = _login(client)
    header, payload, signature = token.split(".")
    first_character = "A" if signature[0] != "A" else "B"
    tampered_signature = first_character + signature[1:]

    response = client.get(
        "/test/reviewer",
        headers={"Authorization": f"Bearer {header}.{payload}.{tampered_signature}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "malformed_token",
    (
        "not-a-token",
        "only.two",
        "four.parts.are.invalid",
        "...",
        "%%%.%%%.%%%",
        "a.a.a",
    ),
)
def test_request_rejects_a_malformed_token(malformed_token: str) -> None:
    client, _ = _client_for(role="reviewer")

    response = client.get(
        "/test/reviewer",
        headers={"Authorization": f"Bearer {malformed_token}"},
    )

    assert response.status_code == 401


def test_first_admin_creation_accepts_password_in_memory_and_stores_only_hash() -> None:
    session = EmptyCapturingSession()

    import asyncio

    admin = asyncio.run(
        create_first_admin(
            session, "  ADMIN@example.com ", "correct horse battery staple"
        )
    )

    assert session.committed
    assert session.added is admin
    assert admin.email == "admin@example.com"
    assert admin.role == "admin"
    assert admin.password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", admin.password_hash)


def test_production_configuration_requires_an_environment_auth_secret(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(ValidationError, match="auth_secret"):
        Settings(
            environment="production",
            postgres_url="postgresql+asyncpg://database/ingestion",
            redis_url="redis://cache:6379/0",
            minio_url="http://objects:9000",
            minio_access_key="configured-outside-source",
            minio_secret_key="configured-outside-source",
        )


def test_configuration_rejects_an_auth_secret_shorter_than_32_bytes() -> None:
    with pytest.raises(ValidationError, match="32 bytes"):
        Settings(environment="test", auth_secret="too-short")


def test_production_worker_configuration_does_not_require_auth_secret(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    settings = Settings(
        environment="production",
        runtime_role="worker",
        postgres_url="postgresql+asyncpg://database/ingestion",
        redis_url="redis://cache:6379/0",
        minio_url="http://objects:9000",
        minio_access_key="configured-outside-source",
        minio_secret_key="configured-outside-source",
    )

    assert settings.auth_secret is None


def test_worker_configuration_ignores_an_irrelevant_short_auth_secret() -> None:
    settings = Settings(
        environment="production",
        runtime_role="worker",
        postgres_url="postgresql+asyncpg://database/ingestion",
        redis_url="redis://cache:6379/0",
        minio_url="http://objects:9000",
        minio_access_key="configured-outside-source",
        minio_secret_key="configured-outside-source",
        auth_secret="irrelevant",
    )

    assert settings.runtime_role == "worker"
