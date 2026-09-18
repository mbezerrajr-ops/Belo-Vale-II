"""Funcionalidades disponíveis nesta instalação.

A leitura de fichas por foto depende de um provedor de OCR. Com o provedor
falso (o padrão, que devolve sempre o mesmo animal), a área "Fichas" não
pode aparecer para a fazenda: uma leitura inventada chegaria à revisão
parecendo verdadeira. Ela só aparece com provedor real, ou com o modo de
demonstração ligado de propósito — que é recusado em produção.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from tests.pg_support import SECRET, api, auth, db, make_user  # noqa: F401 — fixtures


def _features(api, token, settings: Settings) -> dict:
    api.app.dependency_overrides[get_settings] = lambda: settings
    return api.get("/api/features", headers=auth(token)).json()


class TestPhotoSheets:
    def test_hidden_with_the_fake_ocr(self, api, db) -> None:
        _, operator = make_user("operator")

        body = _features(api, operator, Settings(environment="test", auth_secret=SECRET))

        assert body == {"photo_sheets": False}

    def test_shown_with_a_real_ocr_provider(self, api, db) -> None:
        _, operator = make_user("operator")

        body = _features(
            api,
            operator,
            Settings(environment="test", auth_secret=SECRET, vision_provider="http"),
        )

        assert body == {"photo_sheets": True}

    def test_shown_when_the_demo_is_switched_on(self, api, db) -> None:
        _, operator = make_user("operator")

        body = _features(
            api, operator, Settings(environment="test", auth_secret=SECRET, photo_sheets_demo=True)
        )

        assert body == {"photo_sheets": True}

    def test_requires_login(self, api, db) -> None:
        assert api.get("/api/features").status_code == 401


class TestProductionGuard:
    def test_the_demo_is_refused_in_production(self) -> None:
        with pytest.raises(ValidationError, match="photo_sheets_demo"):
            Settings(
                environment="production",
                runtime_role="api",
                postgres_url="postgresql+asyncpg://x/y",
                redis_url="redis://x",
                minio_url="http://x",
                minio_access_key="x",
                minio_secret_key="x",
                auth_secret="x" * 40,
                photo_sheets_demo=True,
            )
