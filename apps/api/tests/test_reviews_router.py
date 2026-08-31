from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.services.storage import InMemoryObjectStorage, get_object_storage


class _UnusedSession:
    """Dependency override so route resolution doesn't fail before the auth
    check runs; unauthenticated requests never actually reach a query."""


def _client() -> TestClient:
    app = create_app()

    async def override_session() -> AsyncIterator[_UnusedSession]:
        yield _UnusedSession()

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: InMemoryObjectStorage()
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test", auth_secret="test-only-secret-with-at-least-32-bytes"
    )
    return TestClient(app)


def test_get_review_requires_authentication() -> None:
    response = _client().get(f"/api/imports/{uuid4()}/review")

    assert response.status_code == 401


def test_decision_requires_authentication() -> None:
    response = _client().post(
        f"/api/extracted-lines/{uuid4()}/decision",
        json={"action": "approve", "expected_version": 1},
    )

    assert response.status_code == 401
