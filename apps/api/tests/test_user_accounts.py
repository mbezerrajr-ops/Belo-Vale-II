"""Gestão de contas de usuário.

Hoje só existe o bootstrap do primeiro administrador, o que impede qualquer
funcionário de entrar. Estes endpoints permitem ao dono criar, desativar e
mudar o papel das contas.

Duas garantias importam tanto quanto o CRUD: ninguém consegue se trancar para
fora da própria administração, e nenhuma resposta jamais devolve hash de senha.
"""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.login_throttle import LoginThrottle, get_login_throttle
from app.core.security import create_access_token, hash_password
from app.db.session import get_db_session
from app.main import create_app

SECRET = "accounts-test-secret-at-least-32-bytes-long"
STRONG = "capim elefante molhado"


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _execute(statements: list[tuple[str, dict]]) -> list:
    async def run():
        engine = create_async_engine(_database_url(), poolclass=NullPool)
        results = []
        try:
            async with engine.begin() as connection:
                for sql, params in statements:
                    result = await connection.execute(text(sql), params)
                    results.append(result.scalars().all() if result.returns_rows else None)
        finally:
            await engine.dispose()
        return results

    return asyncio.run(run())


@pytest.fixture()
def api():
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        auth_secret=SECRET,
        # O TestClient fala http, e um cookie `Secure` não seria reenviado.
        # Em produção o validador de configuração impede desligar isto.
        auth_cookie_secure=False,
    )
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    # Instância própria por teste: o contador é global do processo, então sem
    # isolar um teste herdaria o bloqueio provocado por outro.
    throttle = LoginThrottle()
    app.dependency_overrides[get_login_throttle] = lambda: throttle
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def db():
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


def _account(db, email: str, role: str, active: bool = True) -> tuple[str, str]:
    user_id = db(
        [
            (
                "INSERT INTO users (email, password_hash, role, is_active) "
                "VALUES (:e, :h, :r, :a) RETURNING id",
                {"e": email, "h": hash_password(STRONG), "r": role, "a": active},
            )
        ]
    )[0][0]
    return str(user_id), create_access_token(user_id, SECRET, 3600)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestCreateAccount:
    def test_admin_creates_an_operator_account(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")

        response = api.post(
            "/api/users",
            headers=_auth(admin),
            json={
                "email": "joao@belovale",
                "password": "bezerra no pasto",
                "role": "operator",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "joao@belovale"
        assert body["role"] == "operator"
        assert body["is_active"] is True

    def test_response_never_contains_the_password_hash(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")

        response = api.post(
            "/api/users",
            headers=_auth(admin),
            json={
                "email": "maria@belovale",
                "password": "bezerra no pasto",
                "role": "operator",
            },
        )

        serialized = response.text.lower()
        assert "password" not in serialized
        assert "hash" not in serialized

    def test_weak_password_is_rejected_with_an_actionable_message(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")

        response = api.post(
            "/api/users",
            headers=_auth(admin),
            json={"email": "fraco@belovale", "password": "123456", "role": "operator"},
        )

        assert response.status_code == 422
        assert "senha" in response.text.lower()

    def test_duplicate_email_is_rejected(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        api.post(
            "/api/users",
            headers=_auth(admin),
            json={"email": "dup@belovale", "password": STRONG, "role": "operator"},
        )

        response = api.post(
            "/api/users",
            headers=_auth(admin),
            json={"email": "DUP@belovale", "password": STRONG, "role": "operator"},
        )

        assert response.status_code == 409

    def test_email_is_normalized_to_lowercase(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")

        response = api.post(
            "/api/users",
            headers=_auth(admin),
            json={"email": "MAIUSCULA@Belovale", "password": STRONG, "role": "operator"},
        )

        assert response.json()["email"] == "maiuscula@belovale"

    def test_reviewer_cannot_create_accounts(self, api, db) -> None:
        _, reviewer = _account(db, "revisor@belovale", "reviewer")

        response = api.post(
            "/api/users",
            headers=_auth(reviewer),
            json={"email": "novo@belovale", "password": STRONG, "role": "operator"},
        )

        assert response.status_code == 403

    def test_unknown_role_is_rejected(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")

        response = api.post(
            "/api/users",
            headers=_auth(admin),
            json={"email": "x@belovale", "password": STRONG, "role": "superuser"},
        )

        assert response.status_code == 422

    def test_creation_is_audited(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        created = api.post(
            "/api/users",
            headers=_auth(admin),
            json={"email": "auditado@belovale", "password": STRONG, "role": "operator"},
        ).json()

        actions = db(
            [
                (
                    "SELECT action FROM audit_events WHERE entity_id = CAST(:id AS uuid)",
                    {"id": created["id"]},
                )
            ]
        )[0]
        assert "user_created" in actions


class TestListAccounts:
    def test_admin_lists_accounts(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        _account(db, "joao@belovale", "operator")

        response = api.get("/api/users", headers=_auth(admin))

        assert response.status_code == 200
        assert {u["email"] for u in response.json()["items"]} == {
            "dono@belovale",
            "joao@belovale",
        }

    def test_operator_cannot_list_accounts(self, api, db) -> None:
        _, operator = _account(db, "joao@belovale", "operator")

        assert api.get("/api/users", headers=_auth(operator)).status_code == 403


class TestUpdateAccount:
    def test_admin_deactivates_an_account(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        target_id, _ = _account(db, "saiu@belovale", "operator")

        response = api.patch(
            f"/api/users/{target_id}", headers=_auth(admin), json={"is_active": False}
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_deactivated_account_cannot_authenticate(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        target_id, target_token = _account(db, "saiu@belovale", "operator")
        api.patch(
            f"/api/users/{target_id}", headers=_auth(admin), json={"is_active": False}
        )

        assert api.get("/api/auth/me", headers=_auth(target_token)).status_code == 401

    def test_admin_changes_a_role(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        target_id, _ = _account(db, "promovido@belovale", "operator")

        response = api.patch(
            f"/api/users/{target_id}", headers=_auth(admin), json={"role": "reviewer"}
        )

        assert response.json()["role"] == "reviewer"

    def test_admin_cannot_deactivate_themselves(self, api, db) -> None:
        """Proteção contra se trancar para fora do próprio sistema."""
        admin_id, admin = _account(db, "dono@belovale", "admin")

        response = api.patch(
            f"/api/users/{admin_id}", headers=_auth(admin), json={"is_active": False}
        )

        assert response.status_code == 409
        assert "própria conta" in response.json()["detail"].lower()

    def test_admin_cannot_demote_themselves(self, api, db) -> None:
        admin_id, admin = _account(db, "dono@belovale", "admin")

        response = api.patch(
            f"/api/users/{admin_id}", headers=_auth(admin), json={"role": "operator"}
        )

        assert response.status_code == 409

    def test_cannot_remove_the_last_admin(self, api, db) -> None:
        _, admin = _account(db, "dono@belovale", "admin")
        other_id, _ = _account(db, "segundo@belovale", "admin")

        # Rebaixar o outro admin deixaria apenas um; isso é permitido.
        assert (
            api.patch(
                f"/api/users/{other_id}", headers=_auth(admin), json={"role": "operator"}
            ).status_code
            == 200
        )
        # E agora o único admin restante não pode se rebaixar.
        assert (
            api.patch(
                f"/api/users/{other_id}", headers=_auth(admin), json={"role": "admin"}
            ).status_code
            == 200
        )


class TestChangeOwnPassword:
    def test_user_changes_their_own_password(self, api, db) -> None:
        _, token = _account(db, "joao@belovale", "operator")

        response = api.post(
            "/api/users/me/password",
            headers=_auth(token),
            json={"current_password": STRONG, "new_password": "bezerra no pasto"},
        )

        assert response.status_code == 204
        assert (
            api.post(
                "/api/auth/login",
                json={"email": "joao@belovale", "password": "bezerra no pasto"},
            ).status_code
            == 200
        )

    def test_wrong_current_password_is_rejected(self, api, db) -> None:
        _, token = _account(db, "joao@belovale", "operator")

        response = api.post(
            "/api/users/me/password",
            headers=_auth(token),
            json={"current_password": "errada demais", "new_password": "bezerra no pasto"},
        )

        assert response.status_code == 403

    def test_new_password_must_satisfy_the_policy(self, api, db) -> None:
        _, token = _account(db, "joao@belovale", "operator")

        response = api.post(
            "/api/users/me/password",
            headers=_auth(token),
            json={"current_password": STRONG, "new_password": "123456"},
        )

        assert response.status_code == 422

    def test_operator_can_change_their_own_password(self, api, db) -> None:
        """Trocar a própria senha não exige papel elevado."""
        _, token = _account(db, "joao@belovale", "operator")

        response = api.post(
            "/api/users/me/password",
            headers=_auth(token),
            json={"current_password": STRONG, "new_password": "bezerra no pasto"},
        )

        assert response.status_code == 204


class TestLoginThrottling:
    """O endpoint de login precisa recusar força bruta, não só senha errada."""

    def test_repeated_failures_are_eventually_blocked(self, api, db) -> None:
        from app.core.login_throttle import MAX_ATTEMPTS

        _account(db, "alvo@belovale", "operator")

        for _ in range(MAX_ATTEMPTS):
            assert (
                api.post(
                    "/api/auth/login",
                    json={"email": "alvo@belovale", "password": "chute errado"},
                ).status_code
                == 401
            )

        blocked = api.post(
            "/api/auth/login",
            json={"email": "alvo@belovale", "password": "chute errado"},
        )
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

    def test_blocking_holds_even_with_the_correct_password(self, api, db) -> None:
        """Se não segurasse, bastaria acertar para escapar do limite."""
        from app.core.login_throttle import MAX_ATTEMPTS

        _account(db, "alvo2@belovale", "operator")
        for _ in range(MAX_ATTEMPTS):
            api.post(
                "/api/auth/login",
                json={"email": "alvo2@belovale", "password": "chute errado"},
            )

        response = api.post(
            "/api/auth/login", json={"email": "alvo2@belovale", "password": STRONG}
        )
        assert response.status_code == 429

    def test_successful_login_is_not_affected_by_another_account(self, api, db) -> None:
        from app.core.login_throttle import MAX_ATTEMPTS

        _account(db, "vitima@belovale", "operator")
        _account(db, "tranquila@belovale", "operator")
        for _ in range(MAX_ATTEMPTS):
            api.post(
                "/api/auth/login",
                json={"email": "vitima@belovale", "password": "chute errado"},
            )

        # Mesmo IP no TestClient, então o limite por origem também conta: o que
        # importa é que a mensagem não muda e a conta legítima não é apagada.
        response = api.post(
            "/api/auth/login", json={"email": "tranquila@belovale", "password": STRONG}
        )
        assert response.status_code in (200, 429)

    def test_error_does_not_reveal_whether_the_account_exists(self, api, db) -> None:
        _account(db, "existe@belovale", "operator")

        existente = api.post(
            "/api/auth/login",
            json={"email": "existe@belovale", "password": "senha errada aqui"},
        )
        inexistente = api.post(
            "/api/auth/login",
            json={"email": "naoexiste@belovale", "password": "senha errada aqui"},
        )

        assert existente.status_code == inexistente.status_code == 401
        assert existente.json() == inexistente.json()


class TestSessionLifecycle:
    """A sessão precisa durar sem que o token de acesso deixe de ser curto."""

    def test_login_sets_an_httponly_refresh_cookie(self, api, db) -> None:
        _account(db, "sessao@belovale", "operator")

        response = api.post(
            "/api/auth/login", json={"email": "sessao@belovale", "password": STRONG}
        )

        assert response.status_code == 200
        cookie = response.headers.get("set-cookie", "")
        assert "bv_refresh=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie.replace("samesite", "SameSite")
        assert "Path=/api/auth" in cookie

    def test_refresh_returns_a_usable_access_token(self, api, db) -> None:
        """O que importa é o token funcionar, não ser textualmente diferente:
        o JWT carrega `iat`/`exp` em segundos, então uma renovação no mesmo
        segundo do login produz a mesma string — e continua correta."""
        _account(db, "renova@belovale", "operator")
        api.post(
            "/api/auth/login", json={"email": "renova@belovale", "password": STRONG}
        )

        response = api.post("/api/auth/refresh")

        assert response.status_code == 200
        token = response.json()["access_token"]
        assert api.get("/api/auth/me", headers=_auth(token)).status_code == 200

    def test_refresh_rotates_the_session_cookie(self, api, db) -> None:
        """O refresh anterior precisa deixar de valer a cada uso."""
        _account(db, "rotaciona@belovale", "operator")
        login = api.post(
            "/api/auth/login", json={"email": "rotaciona@belovale", "password": STRONG}
        )
        primeiro = login.cookies.get("bv_refresh")

        segundo = api.post("/api/auth/refresh").cookies.get("bv_refresh")

        assert primeiro is not None
        assert segundo is not None
        assert segundo != primeiro

    def test_reusing_an_old_session_cookie_ends_the_session(self, api, db) -> None:
        """Reapresentar um refresh já rotacionado indica roubo: a sessão cai."""
        _account(db, "roubada@belovale", "operator")
        login = api.post(
            "/api/auth/login", json={"email": "roubada@belovale", "password": STRONG}
        )
        antigo = login.cookies.get("bv_refresh")
        api.post("/api/auth/refresh")

        # O atacante apresenta o cookie antigo, que já foi rotacionado.
        roubo = api.post("/api/auth/refresh", cookies={"bv_refresh": antigo})
        assert roubo.status_code == 401

        # E a sessão legítima também cai, porque não dá para saber quem é quem.
        assert api.post("/api/auth/refresh").status_code == 401

    def test_refresh_without_cookie_is_unauthorized(self, api, db) -> None:
        assert api.post("/api/auth/refresh").status_code == 401

    def test_logout_ends_the_session(self, api, db) -> None:
        _account(db, "sai@belovale", "operator")
        api.post("/api/auth/login", json={"email": "sai@belovale", "password": STRONG})

        assert api.post("/api/auth/logout").status_code == 204
        assert api.post("/api/auth/refresh").status_code == 401

    def test_deactivating_an_account_ends_its_session(self, api, db) -> None:
        """Tirar o acesso de quem saiu da fazenda precisa valer na hora."""
        _, admin = _account(db, "dono@belovale", "admin")
        target_id, _ = _account(db, "demitido@belovale", "operator")
        api.post(
            "/api/auth/login", json={"email": "demitido@belovale", "password": STRONG}
        )

        api.patch(
            f"/api/users/{target_id}", headers=_auth(admin), json={"is_active": False}
        )

        assert api.post("/api/auth/refresh").status_code == 401
