"""Primeiro acesso de uma conta criada pelo administrador.

Decisão do titular (2026-09-18): quem recebe uma conta nova troca a senha no
primeiro acesso. A senha que o administrador digitou passou por duas mãos —
o mesmo risco que a redefinição de senha já trata.

A senha inicial não expira sozinha: a pessoa pode demorar dias para entrar
pela primeira vez, e isso não é motivo para travar a conta. Ela só serve para
escolher outra.
"""

from __future__ import annotations

from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_farm,
    make_user,
    one,
)

INITIAL = "bezerra no pasto"


def _create(api, admin, email="joao@belovale", role="operator"):
    return api.post(
        "/api/users",
        headers=auth(admin),
        json={"email": email, "password": INITIAL, "role": role},
    )


def _login(api, email, password):
    return api.post("/api/auth/login", json={"email": email, "password": password})


class TestFirstAccess:
    def test_new_account_must_choose_its_own_password(self, api, db) -> None:
        make_farm()
        _, admin = make_user("admin", "dono@belovale")

        created = _create(api, admin)
        login = _login(api, "joao@belovale", INITIAL)

        assert created.status_code == 201
        assert created.json()["reset_pending"] is True
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True

    def test_until_then_only_the_password_change_is_reachable(self, api, db) -> None:
        make_farm()
        _, admin = make_user("admin", "dono@belovale")
        _create(api, admin)
        token = _login(api, "joao@belovale", INITIAL).json()["access_token"]

        assert api.get("/api/animals", headers=auth(token)).status_code == 403

        changed = api.post(
            "/api/users/me/password",
            headers=auth(token),
            json={"current_password": INITIAL, "new_password": "pitomba madura no pe"},
        )

        assert changed.status_code == 204
        assert api.get("/api/animals", headers=auth(token)).status_code == 200

    def test_the_initial_password_does_not_expire(self, api, db) -> None:
        make_farm()
        _, admin = make_user("admin", "dono@belovale")
        _create(api, admin)

        row = one(
            "SELECT must_change_password, password_expires_at FROM users "
            "WHERE email = 'joao@belovale'"
        )

        assert row == [(True, None)]
