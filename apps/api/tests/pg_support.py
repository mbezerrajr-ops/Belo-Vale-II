"""Apoio compartilhado dos testes de integração com PostgreSQL.

Os arquivos de teste mais antigos repetem estas fixtures; os novos importam
daqui. Cada teste recebe um engine `NullPool` próprio, porque o
`get_session_factory` da aplicação é cacheado e ficaria preso ao event loop do
primeiro `TestClient`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.login_throttle import InMemoryLoginThrottle, get_login_throttle
from app.core.security import create_access_token, hash_password
from app.db.session import get_db_session
from app.main import create_app

SECRET = "daily-use-test-secret-at-least-32-bytes-long"
PASSWORD = "capim elefante molhado"

#: Ordem obrigatória: filhos antes dos pais.
_CLEANUP = (
    "DELETE FROM audit_events",
    "DELETE FROM official_measurements",
    "DELETE FROM production_imports",
    "DELETE FROM event_proposals",
    "DELETE FROM event_proposal_sources",
    "DELETE FROM validation_alerts",
    "DELETE FROM review_decisions",
    "DELETE FROM extracted_lines",
    "DELETE FROM extraction_runs",
    "DELETE FROM image_assets",
    "DELETE FROM supply_diets",
    "DELETE FROM supply_prices",
    "DELETE FROM supplies",
    "DELETE FROM animal_lot_assignments",
    "DELETE FROM animals",
    "DELETE FROM baseline_imports",
    "DELETE FROM imports",
    "DELETE FROM farms",
    "DELETE FROM users",
)


def database_url() -> str:
    url = os.getenv("POSTGRES_URL")
    if not url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return url


Execute = Callable[[list[tuple[str, dict]]], list]


def execute(statements: list[tuple[str, dict]]) -> list:
    """SQL de apoio fora da aplicação, para preparar e conferir estado."""

    async def run():
        engine = create_async_engine(database_url(), poolclass=NullPool)
        results = []
        try:
            async with engine.begin() as connection:
                for sql, params in statements:
                    result = await connection.execute(text(sql), params)
                    results.append(result.all() if result.returns_rows else None)
        finally:
            await engine.dispose()
        return results

    return asyncio.run(run())


def one(sql: str, **params) -> list:
    """Linhas de uma consulta só."""
    return execute([(sql, params)])[0]


@pytest.fixture()
def db() -> Execute:
    execute([(sql, {}) for sql in _CLEANUP])
    return execute


@pytest.fixture()
def api():
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        auth_secret=SECRET,
        # O TestClient fala http; um cookie `Secure` não seria reenviado.
        auth_cookie_secure=False,
    )
    engine = create_async_engine(database_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    throttle = InMemoryLoginThrottle()
    app.dependency_overrides[get_login_throttle] = lambda: throttle
    with TestClient(app) as client:
        yield client


def make_user(role: str, email: str | None = None) -> tuple[str, str]:
    """Cria uma conta e devolve ``(id, token)``."""
    email = email or f"{role}@belovale"
    user_id = one(
        "INSERT INTO users (email, password_hash, role, is_active) "
        "VALUES (:e, :h, :r, true) RETURNING id",
        e=email,
        h=hash_password(PASSWORD),
        r=role,
    )[0][0]
    return str(user_id), create_access_token(user_id, SECRET, 3600)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_farm(name: str = "Belo Vale II") -> str:
    return str(one("INSERT INTO farms (name) VALUES (:n) RETURNING id", n=name)[0][0])


def make_animal(
    farm_id: str,
    *,
    brinco: str | None,
    name: str,
    lote: str | None = None,
    kind: str = "diet",
    lot_since: date = date(2026, 1, 1),
    situacao: str = "Em lactação",
) -> str:
    identifier = brinco or f"sem-brinco-{name}"
    animal_id = str(
        one(
            "INSERT INTO animals (farm_id, identifier, brinco, name, situacao, status) "
            "VALUES (:f, :i, :b, :n, :s, 'Ativo') RETURNING id",
            f=farm_id,
            i=identifier,
            b=brinco,
            n=name,
            s=situacao,
        )[0][0]
    )
    if lote:
        one(
            "INSERT INTO animal_lot_assignments "
            "(animal_id, lote, kind, valid_from, source) "
            "VALUES (:a, :l, :k, :v, 'manual') RETURNING id",
            a=animal_id,
            l=lote,
            k=kind,
            v=lot_since,
        )
    return animal_id


__all__ = [
    "PASSWORD",
    "SECRET",
    "TestClient",
    "api",
    "auth",
    "db",
    "execute",
    "make_animal",
    "make_farm",
    "make_user",
    "one",
]
