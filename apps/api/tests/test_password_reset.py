"""Redefinição de senha pelo administrador.

Funcionário que esquece a senha não tinha saída: só criando outra conta, o
que perde o histórico de quem lançou o quê. Aqui o administrador gera uma
senha provisória e a repassa (de viva voz, por mensagem). Como essa senha
passa por mais mãos que uma senha comum, ela:

- é gerada pelo servidor, não escolhida pelo administrador;
- aparece uma única vez, na resposta — nunca na auditoria nem no banco;
- expira sozinha;
- só dá acesso à troca de senha até o usuário escolher uma nova;
- derruba as sessões abertas da conta, porque quem pediu a redefinição pode
  estar justamente perdendo o controle dela.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.password_policy import validate_password
from app.core.temporary_password import TEMPORARY_PASSWORD_TTL, generate_temporary_password
from tests.pg_support import (  # noqa: F401 — fixtures
    PASSWORD,
    api,
    auth,
    db,
    make_farm,
    make_user,
    one,
)


@pytest.fixture()
def people(db):
    make_farm()
    admin_id, admin = make_user("admin", "dono@belovale")
    joao_id, _ = make_user("operator", "joao@belovale")
    return {"admin": admin, "admin_id": admin_id, "joao_id": joao_id}


def _reset(api, token, user_id):
    return api.post(f"/api/users/{user_id}/password-reset", headers=auth(token))


def _login(api, email, password):
    return api.post("/api/auth/login", json={"email": email, "password": password})


class TestGeneration:
    def test_generated_passwords_pass_the_policy(self) -> None:
        for _ in range(200):
            validate_password(generate_temporary_password(), email="joao@belovale")

    def test_generated_passwords_are_not_repeated(self) -> None:
        assert len({generate_temporary_password() for _ in range(200)}) == 200


class TestReset:
    def test_admin_gets_a_temporary_password_once(self, api, people) -> None:
        response = _reset(api, people["admin"], people["joao_id"])

        assert response.status_code == 200
        body = response.json()
        temporary = body["temporary_password"]
        expires_at = datetime.fromisoformat(body["expires_at"])
        remaining = expires_at - datetime.now(timezone.utc)
        assert TEMPORARY_PASSWORD_TTL - timedelta(minutes=1) < remaining <= TEMPORARY_PASSWORD_TTL

        # O valor não fica em lugar nenhum além da resposta.
        stored = one(
            "SELECT password_hash, must_change_password FROM users WHERE id = :u",
            u=people["joao_id"],
        )
        assert temporary not in stored[0][0]
        assert stored[0][1] is True
        audit = one(
            "SELECT action, actor, coalesce(new_value::text, '') FROM audit_events "
            "WHERE entity_id = :u",
            u=people["joao_id"],
        )
        assert audit[0][:2] == ("user_password_reset", "dono@belovale")
        assert temporary not in audit[0][2]

    def test_the_old_password_stops_working(self, api, people) -> None:
        _reset(api, people["admin"], people["joao_id"])

        assert _login(api, "joao@belovale", PASSWORD).status_code == 401

    def test_open_sessions_are_revoked(self, api, people) -> None:
        assert _login(api, "joao@belovale", PASSWORD).status_code == 200
        refresh_cookie = api.cookies.get("bv_refresh")
        assert refresh_cookie

        _reset(api, people["admin"], people["joao_id"])

        response = api.post("/api/auth/refresh", cookies={"bv_refresh": refresh_cookie})
        assert response.status_code == 401

    def test_only_admins_can_reset(self, api, people) -> None:
        _, reviewer = make_user("reviewer", "revisor@belovale")

        assert _reset(api, reviewer, people["joao_id"]).status_code == 403

    def test_admin_cannot_reset_own_password_this_way(self, api, people) -> None:
        """Para a própria senha existe a troca normal, que pede a atual."""
        response = _reset(api, people["admin"], people["admin_id"])

        assert response.status_code == 409

    def test_unknown_account_is_404(self, api, people) -> None:
        response = _reset(api, people["admin"], "00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404


class TestFirstAccess:
    def _temporary(self, api, people) -> str:
        return _reset(api, people["admin"], people["joao_id"]).json()["temporary_password"]

    def test_login_signals_that_the_password_must_change(self, api, people) -> None:
        temporary = self._temporary(api, people)

        response = _login(api, "joao@belovale", temporary)

        assert response.status_code == 200
        assert response.json()["must_change_password"] is True

    def test_only_the_password_change_is_reachable(self, api, people) -> None:
        temporary = self._temporary(api, people)
        token = _login(api, "joao@belovale", temporary).json()["access_token"]

        blocked = api.get("/api/animals", headers=auth(token))
        me = api.get("/api/auth/me", headers=auth(token))

        assert blocked.status_code == 403
        assert "senha" in blocked.json()["detail"].lower()
        assert me.status_code == 200
        assert me.json()["must_change_password"] is True

    def test_choosing_a_new_password_releases_the_account(self, api, people) -> None:
        temporary = self._temporary(api, people)
        token = _login(api, "joao@belovale", temporary).json()["access_token"]

        changed = api.post(
            "/api/users/me/password",
            headers=auth(token),
            json={"current_password": temporary, "new_password": "pitomba madura no pe"},
        )

        assert changed.status_code == 204
        assert api.get("/api/animals", headers=auth(token)).status_code == 200
        row = one(
            "SELECT must_change_password, password_expires_at FROM users WHERE id = :u",
            u=people["joao_id"],
        )
        assert row == [(False, None)]

    def test_the_new_password_must_differ_from_the_temporary_one(
        self, api, people
    ) -> None:
        temporary = self._temporary(api, people)
        token = _login(api, "joao@belovale", temporary).json()["access_token"]

        response = api.post(
            "/api/users/me/password",
            headers=auth(token),
            json={"current_password": temporary, "new_password": temporary},
        )

        assert response.status_code == 422

    def test_an_expired_temporary_password_is_refused(self, api, people) -> None:
        temporary = self._temporary(api, people)
        one(
            "UPDATE users SET password_expires_at = now() - interval '1 minute' "
            "WHERE id = :u RETURNING id",
            u=people["joao_id"],
        )

        response = _login(api, "joao@belovale", temporary)

        assert response.status_code == 401
        assert "expir" in response.json()["detail"].lower()

    def test_an_expired_password_does_not_reveal_itself_to_a_wrong_guess(
        self, api, people
    ) -> None:
        """A mensagem de expiração só aparece para quem acertou a senha: para
        um palpite errado, a resposta é a genérica de sempre."""
        self._temporary(api, people)
        one(
            "UPDATE users SET password_expires_at = now() - interval '1 minute' "
            "WHERE id = :u RETURNING id",
            u=people["joao_id"],
        )

        response = _login(api, "joao@belovale", "palpite totalmente errado")

        assert response.status_code == 401
        assert "expir" not in response.json()["detail"].lower()
