"""Histórico de preço dos insumos.

Mudar o preço do concentrado não apaga o anterior: cada preço fica com a data
em que passou a valer e quem o registrou. O sistema antigo mostrava esse
histórico; aqui ele já era gravado e agora também é lido.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_farm,
    make_user,
    one,
)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _supply(api, token, name="Concentrado", price=2.12):
    return api.post(
        "/api/supplies", headers=auth(token), json={"name": name, "price_per_kg": price}
    ).json()


class TestPriceHistory:
    def test_lists_prices_newest_first_with_who_recorded(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        supply = _supply(api, reviewer)
        api.patch(
            f"/api/supplies/{supply['id']}",
            headers=auth(reviewer),
            json={"price_per_kg": 2.35, "effective_on": "2026-10-01"},
        )

        response = api.get(f"/api/supplies/{supply['id']}/prices", headers=auth(reviewer))

        assert response.status_code == 200
        body = response.json()
        assert [(p["price_per_kg"], p["recorded_by"]) for p in body] == [
            (2.35, "reviewer@belovale"),
            (2.12, "reviewer@belovale"),
        ]
        assert body[0]["effective_on"] == "2026-10-01"

    def test_operator_can_read(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _, operator = make_user("operator")
        supply = _supply(api, reviewer)

        response = api.get(f"/api/supplies/{supply['id']}/prices", headers=auth(operator))

        assert response.status_code == 200

    def test_unknown_supply_is_404(self, api, farm) -> None:
        _, operator = make_user("operator")

        response = api.get(
            "/api/supplies/00000000-0000-0000-0000-000000000000/prices",
            headers=auth(operator),
        )

        assert response.status_code == 404

    def test_price_starts_on_the_farm_day_not_the_server_day(self, api, farm) -> None:
        """Às 22h no Nordeste o servidor em UTC já está no dia seguinte."""
        _, reviewer = make_user("reviewer")

        with patch("app.routers.dashboard.farm_today", return_value=__import__("datetime").date(2026, 9, 18)):
            supply = _supply(api, reviewer)

        effective = one(
            "SELECT effective_on::text FROM supply_prices WHERE supply_id = :s",
            s=supply["id"],
        )
        assert effective == [("2026-09-18",)]
