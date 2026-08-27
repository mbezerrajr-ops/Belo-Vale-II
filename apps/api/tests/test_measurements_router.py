from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app


class _UnusedSession:
    """Unauthenticated requests never reach a query; this only satisfies
    dependency resolution so it doesn't fail before the auth check runs."""


def test_get_measurements_requires_authentication() -> None:
    app = create_app()

    async def override_session() -> AsyncIterator[_UnusedSession]:
        yield _UnusedSession()

    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)

    response = client.get(f"/api/measurements?farm_id={uuid4()}")

    assert response.status_code == 401
