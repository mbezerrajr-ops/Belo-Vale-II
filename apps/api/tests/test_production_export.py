"""Exportação da produção de um período para planilha.

O que precisa valer:

- só o que está valendo: leitura substituída ou anulada não entra;
- só o período pedido, em ordem de data, lote e brinco;
- o lote é o do dia, mesmo nas leituras antigas que não o guardaram;
- o brinco continua texto ("016" não vira 16) e nenhum texto vira fórmula;
- é de revisor ou administrador, e cada exportação fica na auditoria.
"""

from __future__ import annotations

import io
import json
from datetime import date

import pytest
from openpyxl import load_workbook

from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_animal,
    make_farm,
    make_user,
    one,
)

SET_01 = date(2026, 9, 1)
SET_02 = date(2026, 9, 2)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _enter(api, token, animal_id, measured_on, **liters):
    response = api.post(
        "/api/production",
        headers=auth(token),
        json={"animal_id": animal_id, "measured_on": measured_on.isoformat(), **liters},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _export(api, token, inicio, fim):
    return api.get(
        "/api/production/export",
        headers=auth(token),
        params={"inicio": inicio.isoformat(), "fim": fim.isoformat()},
    )


def _rows(response) -> list[tuple]:
    sheet = load_workbook(io.BytesIO(response.content)).active
    return [tuple(cell.value for cell in row) for row in sheet.iter_rows()]


def _baseline_reading(farm_id: str, animal_id: str, day: date, producao: float) -> None:
    """Leitura da base antiga: sem lote gravado na própria leitura."""
    baseline = one(
        "INSERT INTO baseline_imports (farm_id, source_path, source_sha256, "
        "animal_count, measurement_count, approved_by, approved_at) "
        "VALUES (:f, 'x', 'y', 1, 1, 'dono', now()) RETURNING id",
        f=farm_id,
    )[0][0]
    one(
        "INSERT INTO official_measurements (animal_id, measured_on, values, status, "
        "provenance, baseline_import_id, reviewed_by) VALUES "
        "(:a, :d, CAST(:v AS jsonb), 'active', 'legacy_baseline', :b, 'dono') RETURNING id",
        a=animal_id,
        d=day,
        v=json.dumps({"producao": producao}),
        b=baseline,
    )


class TestExport:
    def test_one_line_per_cow_per_day_in_order(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        agata = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 2")
        belmonte = make_animal(farm, brinco="016", name="BELMONTE", lote="LOTE 1")
        _enter(api, reviewer, agata, SET_02, manha=8, tarde=6.5, observacao="secar")
        _enter(api, reviewer, agata, SET_01, producao=12)
        _enter(api, reviewer, belmonte, SET_01, manha=5.5, tarde=4)

        response = _export(api, reviewer, SET_01, SET_02)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert 'filename="producao-2026-09-01-a-2026-09-02.xlsx"' in response.headers["content-disposition"]
        assert response.headers["x-leituras"] == "3"
        header, *rows = _rows(response)
        assert header == ("Data", "Lote", "Brinco", "Nome", "Manhã (L)", "Tarde (L)", "Total (L)", "Observação")
        assert [(r[0].date(), *r[1:]) for r in rows] == [
            (SET_01, "LOTE 1", "016", "BELMONTE", 5.5, 4, 9.5, None),
            (SET_01, "LOTE 2", "389", "ÁGATA", None, None, 12, None),
            (SET_02, "LOTE 2", "389", "ÁGATA", 8, 6.5, 14.5, "secar"),
        ]

    def test_only_what_is_in_force_and_in_the_period(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 2")
        other = make_animal(farm, brinco="417", name="PANDORA", lote="LOTE 2")
        corrected = _enter(api, reviewer, cow, SET_01, producao=12)
        correction = api.post(
            f"/api/production/{corrected['id']}/correction",
            headers=auth(reviewer),
            json={"producao": 13, "reason": "digitação"},
        )
        assert correction.status_code == 201, correction.text
        voided = _enter(api, reviewer, other, SET_01, producao=9)
        void = api.post(f"/api/production/{voided['id']}/void", headers=auth(reviewer), json={"reason": "vaca errada"})
        assert void.status_code == 204, void.text
        _enter(api, reviewer, cow, date(2026, 8, 31), producao=11)

        _, *rows = _rows(_export(api, reviewer, SET_01, SET_02))

        assert [(r[2], r[6]) for r in rows] == [("389", 13)]

    def test_old_readings_take_the_lot_of_the_day(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 3", lot_since=date(2026, 1, 1))
        _baseline_reading(farm, cow, SET_01, 10)

        _, *rows = _rows(_export(api, reviewer, SET_01, SET_01))

        assert [r[1] for r in rows] == ["LOTE 3"]

    def test_text_stays_text(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="016", name="=HYPERLINK(\"http://x\")", lote="LOTE 1")
        _enter(api, reviewer, cow, SET_01, producao=10)

        sheet = load_workbook(io.BytesIO(_export(api, reviewer, SET_01, SET_01).content)).active

        assert sheet["C2"].value == "016"
        assert sheet["C2"].data_type == "s"
        assert sheet["D2"].data_type == "s"
        assert sheet["D2"].value == '=HYPERLINK("http://x")'

    def test_empty_period_says_so(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")

        response = _export(api, reviewer, SET_01, SET_02)

        assert response.status_code == 200
        assert response.headers["x-leituras"] == "0"
        assert len(_rows(response)) == 1

    def test_operator_cannot_export(self, api, farm) -> None:
        _, operator = make_user("operator")

        assert _export(api, operator, SET_01, SET_02).status_code == 403

    def test_end_before_start_is_refused(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")

        response = _export(api, reviewer, SET_02, SET_01)

        assert response.status_code == 422
        assert "antes da inicial" in response.json()["detail"]

    def test_at_most_a_year(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")

        assert _export(api, reviewer, date(2025, 9, 1), date(2026, 9, 1)).status_code == 200
        assert _export(api, reviewer, date(2025, 9, 1), date(2026, 9, 2)).status_code == 422

    def test_each_export_is_audited(self, api, farm) -> None:
        _, admin = make_user("admin")

        _export(api, admin, SET_01, SET_02)

        assert one("SELECT actor, new_value::text FROM audit_events WHERE action = 'production_exported'") == [
            ("admin@belovale", '{"fim": "2026-09-02", "inicio": "2026-09-01", "leituras": 0}')
        ]
