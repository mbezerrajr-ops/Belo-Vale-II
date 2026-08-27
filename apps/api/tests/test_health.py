from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.core.config import Settings
from app.main import create_app


def test_healthz_returns_ok() -> None:
    response = TestClient(create_app()).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_production_settings_require_infrastructure_urls_and_credentials() -> None:
    with pytest.raises(ValidationError, match="Missing required production settings"):
        Settings(environment="production")
