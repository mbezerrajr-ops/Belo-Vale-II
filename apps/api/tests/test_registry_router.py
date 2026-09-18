"""API do cadastro mestre.

Cobre o contrato HTTP e o RBAC. Verifica também a decisão de monofazenda: a
API resolve a fazenda no servidor e **não** aceita `farm_id` vindo do cliente.
"""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_db_session
from app.main import create_app

SECRET = "registry-test-secret-at-least-32-bytes-long"


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _execute(statements: list[tuple[str, dict]]) -> list:
    """Executa SQL de apoio fora da aplicação, para preparar e conferir estado."""

    async def run():
        engine = create_async_engine(_database_url(), poolclass=NullPool)
        results = []
        try:
            async with engine.begin() as connection:
                for sql, params in statements:
                    result = await connection.execute(text(sql), params)
                    if result.returns_rows:
                        results.append(result.scalars().all())
                    else:
                        results.append(None)
        finally:
            await engine.dispose()
        return results

    return asyncio.run(run())


@pytest.fixture()
def api():
    """App com sessão própria por teste.

    `get_session_factory` é cacheado, então o engine da aplicação ficaria preso
    ao event loop do primeiro TestClient. Injetar um engine com `NullPool`
    mantém cada teste independente e não deixa conexões presas a loops já
    fechados.
    """
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test", auth_secret=SECRET
    )
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def db():
    """Base limpa: o cadastro é sobre estado global da fazenda."""
    # Ordem obrigatória: as FKs do pipeline de ingestão apontam para farms, e
    # outros testes da suíte deixam linhas dessas tabelas para trás.
    _execute(
        [
            ("DELETE FROM audit_events", {}),
            ("DELETE FROM official_measurements", {}),
            ("DELETE FROM validation_alerts", {}),
            ("DELETE FROM review_decisions", {}),
            ("DELETE FROM extracted_lines", {}),
            ("DELETE FROM extraction_runs", {}),
            ("DELETE FROM image_assets", {}),
            ("DELETE FROM supply_diets", {}),
            ("DELETE FROM supply_prices", {}),
            ("DELETE FROM supplies", {}),
            ("DELETE FROM animal_lot_assignments", {}),
            ("DELETE FROM animals", {}),
            ("DELETE FROM baseline_imports", {}),
            ("DELETE FROM imports", {}),
            ("DELETE FROM farms", {}),
            ("DELETE FROM users", {}),
        ]
    )
    return _execute


def _user(db, email: str, role: str) -> str:
    user_id = db(
        [
            (
                "INSERT INTO users (email, password_hash, role, is_active) "
                "VALUES (:email, :hash, :role, true) RETURNING id",
                {
                    "email": email,
                    "hash": hash_password("uma senha bem longa"),
                    "role": role,
                },
            )
        ]
    )[0][0]
    return create_access_token(user_id, SECRET, 3600)


def _farm(db, name: str = "Belo Vale II") -> str:
    return str(
        db(
            [
                (
                    "INSERT INTO farms (name) VALUES (:name) RETURNING id",
                    {"name": name},
                )
            ]
        )[0][0]
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestCurrentFarm:
    def test_returns_the_single_farm(self, api, db) -> None:
        farm_id = _farm(db)
        token = _user(db, "operador@belovale", "operator")

        response = api.get("/api/farms/current", headers=_auth(token))

        assert response.status_code == 200
        assert response.json()["id"] == farm_id

    def test_reports_when_no_farm_exists(self, api, db) -> None:
        token = _user(db, "operador@belovale", "operator")

        response = api.get("/api/farms/current", headers=_auth(token))

        assert response.status_code == 409
        assert "nenhuma fazenda" in response.json()["detail"].lower()

    def test_requires_authentication(self, api, db) -> None:
        _farm(db)
        assert api.get("/api/farms/current").status_code in (401, 403)


class TestCreateFarm:
    def test_admin_creates_the_first_farm(self, api, db) -> None:
        token = _user(db, "admin@belovale", "admin")

        response = api.post(
            "/api/farms", headers=_auth(token), json={"name": "Belo Vale II"}
        )

        assert response.status_code == 201
        assert response.json()["name"] == "Belo Vale II"

    def test_reviewer_cannot_create_a_farm(self, api, db) -> None:
        token = _user(db, "revisor@belovale", "reviewer")

        response = api.post("/api/farms", headers=_auth(token), json={"name": "Outra"})

        assert response.status_code == 403


class TestAnimalsEndpoints:
    def test_reviewer_creates_an_animal(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")

        response = api.post(
            "/api/animals",
            headers=_auth(token),
            json={"brinco": "b2- 008", "name": "Cabelo de Fogo", "lote": "LOTE 1"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["brinco"] == "B2-008"
        assert body["lote_atual"] == "LOTE 1"

    def test_operator_cannot_create_an_animal(self, api, db) -> None:
        _farm(db)
        token = _user(db, "operador@belovale", "operator")

        response = api.post(
            "/api/animals", headers=_auth(token), json={"brinco": "500", "name": "X"}
        )

        assert response.status_code == 403

    def test_operator_can_list_animals(self, api, db) -> None:
        _farm(db)
        reviewer = _user(db, "revisor@belovale", "reviewer")
        api.post(
            "/api/animals",
            headers=_auth(reviewer),
            json={"brinco": "501", "name": "LISTADA"},
        )
        operator = _user(db, "operador@belovale", "operator")

        response = api.get("/api/animals", headers=_auth(operator))

        assert response.status_code == 200
        assert [a["name"] for a in response.json()["items"]] == ["LISTADA"]

    def test_farm_id_sent_by_the_client_is_ignored(self, api, db) -> None:
        """Decisão de monofazenda: a fazenda vem do servidor."""
        farm_id = _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        inventada = "00000000-0000-0000-0000-000000000123"

        response = api.post(
            "/api/animals",
            headers=_auth(token),
            json={"brinco": "502", "name": "ALVO", "farm_id": inventada},
        )

        assert response.status_code == 201
        assert response.json()["farm_id"] == farm_id
        stored = db([("SELECT farm_id FROM animals WHERE brinco = '502'", {})])[0][0]
        assert str(stored) == farm_id

    def test_refuses_to_guess_when_more_than_one_farm_exists(self, api, db) -> None:
        """Ambiguidade não é resolvida por chute: falhar é mais seguro."""
        _farm(db)
        _farm(db, "Fazenda alheia")
        token = _user(db, "revisor@belovale", "reviewer")

        response = api.post(
            "/api/animals", headers=_auth(token), json={"brinco": "503", "name": "X"}
        )

        assert response.status_code == 409
        assert "monofazenda" in response.json()["detail"].lower()

    def test_search_by_brinco(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        for brinco, name in (("600", "PRIMEIRA"), ("601", "SEGUNDA")):
            api.post(
                "/api/animals",
                headers=_auth(token),
                json={"brinco": brinco, "name": name},
            )

        response = api.get("/api/animals?brinco=601", headers=_auth(token))

        assert [a["name"] for a in response.json()["items"]] == ["SEGUNDA"]

    def test_duplicate_brinco_is_rejected_with_409(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        api.post(
            "/api/animals", headers=_auth(token), json={"brinco": "700", "name": "A"}
        )

        response = api.post(
            "/api/animals", headers=_auth(token), json={"brinco": "700", "name": "B"}
        )

        assert response.status_code == 409

    def test_detail_includes_lot_history(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        created = api.post(
            "/api/animals",
            headers=_auth(token),
            json={
                "brinco": "800",
                "name": "COM HISTORICO",
                "lote": "LOTE 1",
                "lote_valid_from": "2026-01-01",
            },
        ).json()
        api.post(
            f"/api/animals/{created['id']}/lote",
            headers=_auth(token),
            json={"lote": "LOTE 2", "valid_from": "2026-06-01"},
        )

        response = api.get(f"/api/animals/{created['id']}", headers=_auth(token))

        assert response.status_code == 200
        history = response.json()["historico_lotes"]
        assert [h["lote"] for h in history] == ["LOTE 1", "LOTE 2"]
        assert history[0]["valid_to"] == "2026-05-31"
        assert history[1]["valid_to"] is None


class TestLinkBrincoEndpoint:
    def test_links_brinco_with_evidence(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        created = api.post(
            "/api/animals", headers=_auth(token), json={"name": "SEM BRINCO"}
        ).json()

        response = api.post(
            f"/api/animals/{created['id']}/brinco",
            headers=_auth(token),
            json={"brinco": "B1-900", "evidence": "Conferido no curral"},
        )

        assert response.status_code == 200
        assert response.json()["brinco"] == "B1-900"

    def test_evidence_is_required(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        created = api.post(
            "/api/animals", headers=_auth(token), json={"name": "SEM EVIDENCIA"}
        ).json()

        response = api.post(
            f"/api/animals/{created['id']}/brinco",
            headers=_auth(token),
            json={"brinco": "B1-901", "evidence": "  "},
        )

        assert response.status_code in (400, 422)

    def test_operator_cannot_link_brinco(self, api, db) -> None:
        _farm(db)
        reviewer = _user(db, "revisor@belovale", "reviewer")
        created = api.post(
            "/api/animals", headers=_auth(reviewer), json={"name": "PROTEGIDA"}
        ).json()
        operator = _user(db, "operador@belovale", "operator")

        response = api.post(
            f"/api/animals/{created['id']}/brinco",
            headers=_auth(operator),
            json={"brinco": "B1-902", "evidence": "tentativa"},
        )

        assert response.status_code == 403


class TestUpdateAnimalEndpoint:
    def test_renames_and_audits(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        created = api.post(
            "/api/animals", headers=_auth(token), json={"brinco": "900", "name": "KAROLINA"}
        ).json()

        response = api.patch(
            f"/api/animals/{created['id']}",
            headers=_auth(token),
            json={"name": "Carolina"},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Carolina"
        actions = db(
            [
                (
                    "SELECT action FROM audit_events WHERE entity_id = CAST(:id AS uuid) "
                    "ORDER BY created_at",
                    {"id": created["id"]},
                )
            ]
        )[0]
        assert "animal_updated" in actions

    def test_cannot_change_brinco_through_patch(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        created = api.post(
            "/api/animals", headers=_auth(token), json={"brinco": "901", "name": "Z"}
        ).json()

        response = api.patch(
            f"/api/animals/{created['id']}",
            headers=_auth(token),
            json={"brinco": "902"},
        )

        assert response.status_code in (400, 422)


class TestDashboardEndpoint:
    def test_operator_reads_the_dashboard(self, api, db) -> None:
        _farm(db)
        token = _user(db, "operador@belovale", "operator")

        response = api.get("/api/dashboard", headers=_auth(token))

        assert response.status_code == 200
        body = response.json()
        assert body["total_animals"] == 0
        assert body["lots"] == []

    def test_dashboard_requires_authentication(self, api, db) -> None:
        _farm(db)
        assert api.get("/api/dashboard").status_code in (401, 403)

    def test_dashboard_reflects_supplies_and_animals(self, api, db) -> None:
        farm_id = _farm(db)
        reviewer = _user(db, "revisor@belovale", "reviewer")

        api.patch(
            "/api/farms/current/milk-price",
            headers=_auth(reviewer),
            json={"milk_price_per_liter": 2.5},
        )
        supply = api.post(
            "/api/supplies",
            headers=_auth(reviewer),
            json={"name": "Silagem", "price_per_kg": 0.5},
        ).json()
        api.put(
            f"/api/supplies/{supply['id']}/diet",
            headers=_auth(reviewer),
            json={"lote": "LOTE 1", "kg_per_day": 100},
        )
        api.post(
            "/api/animals",
            headers=_auth(reviewer),
            json={"brinco": "700", "name": "AURORA", "lote": "LOTE 1"},
        )

        body = api.get("/api/dashboard", headers=_auth(reviewer)).json()

        assert body["milk_price"] == 2.5
        lot = next(l for l in body["lots"] if l["lote"] == "LOTE 1")
        assert lot["feed_cost"] == 50.0
        assert lot["animals"] == 1
        assert lot["cost_per_animal"] == 50.0


class TestSuppliesEndpoints:
    def test_reviewer_creates_a_supply(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")

        response = api.post(
            "/api/supplies",
            headers=_auth(token),
            json={"name": "Concentrado", "price_per_kg": 2.12},
        )

        assert response.status_code == 201
        assert response.json()["name"] == "Concentrado"

    def test_operator_cannot_create_a_supply(self, api, db) -> None:
        _farm(db)
        token = _user(db, "operador@belovale", "operator")

        response = api.post(
            "/api/supplies",
            headers=_auth(token),
            json={"name": "Milho", "price_per_kg": 1.0},
        )

        assert response.status_code == 403

    def test_operator_can_read_supplies(self, api, db) -> None:
        _farm(db)
        reviewer = _user(db, "revisor@belovale", "reviewer")
        api.post(
            "/api/supplies",
            headers=_auth(reviewer),
            json={"name": "Silagem", "price_per_kg": 0.35},
        )
        operator = _user(db, "operador@belovale", "operator")

        response = api.get("/api/supplies", headers=_auth(operator))

        assert response.status_code == 200
        assert [s["name"] for s in response.json()] == ["Silagem"]

    def test_duplicate_supply_name_is_rejected(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        api.post(
            "/api/supplies",
            headers=_auth(token),
            json={"name": "Silagem", "price_per_kg": 0.35},
        )

        response = api.post(
            "/api/supplies",
            headers=_auth(token),
            json={"name": "Silagem", "price_per_kg": 0.40},
        )

        assert response.status_code == 409

    def test_price_change_keeps_the_previous_in_history(self, api, db) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        supply = api.post(
            "/api/supplies",
            headers=_auth(token),
            json={"name": "Silagem", "price_per_kg": 0.35},
        ).json()

        api.patch(
            f"/api/supplies/{supply['id']}",
            headers=_auth(token),
            json={"price_per_kg": 0.42, "effective_on": "2026-09-18"},
        )

        prices = db(
            [
                (
                    "SELECT price_per_kg FROM supply_prices "
                    "WHERE supply_id = CAST(:id AS uuid) ORDER BY effective_on",
                    {"id": supply["id"]},
                )
            ]
        )[0]
        assert len(prices) == 2

    def test_setting_the_diet_twice_updates_instead_of_duplicating(
        self, api, db
    ) -> None:
        _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")
        supply = api.post(
            "/api/supplies",
            headers=_auth(token),
            json={"name": "Silagem", "price_per_kg": 0.35},
        ).json()

        api.put(
            f"/api/supplies/{supply['id']}/diet",
            headers=_auth(token),
            json={"lote": "LOTE 1", "kg_per_day": 100},
        )
        response = api.put(
            f"/api/supplies/{supply['id']}/diet",
            headers=_auth(token),
            json={"lote": "LOTE 1", "kg_per_day": 120},
        )

        diets = response.json()["diets"]
        assert diets == [{"lote": "LOTE 1", "kg_per_day": 120.0}]

    def test_milk_price_change_is_audited(self, api, db) -> None:
        farm_id = _farm(db)
        token = _user(db, "revisor@belovale", "reviewer")

        api.patch(
            "/api/farms/current/milk-price",
            headers=_auth(token),
            json={"milk_price_per_liter": 3.15},
        )

        actions = db(
            [
                (
                    "SELECT action FROM audit_events WHERE entity_id = CAST(:id AS uuid)",
                    {"id": farm_id},
                )
            ]
        )[0]
        assert "milk_price_changed" in actions
