"""Manhã, tarde e observação de cada vaca na pesagem.

A fazenda pesa nas duas ordenhas e anota o manejo na mesma folha ("→ Seca",
"→ 3º Lote"). Até aqui o sistema guardava só o total, e a folha impressa
saía sem litros e sem observação. O que estes testes fixam:

- manhã e tarde ficam guardadas, e o total é a soma delas;
- completar a parte que falta (a tarde lançada depois da manhã, a
  observação anotada depois) não é correção: é livre, e a versão anterior
  fica no histórico;
- mudar uma parte já lançada continua sendo conflito, como mudar o total;
- a planilha no formato da fazenda (título em cima, "Nº Vaca", manhã, tarde,
  total e observação) entra direto, e a linha em que manhã + tarde não bate
  com o total é apontada, não gravada;
- a folha traz a pesagem anterior de cada vaca, para a folha em branco.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from app.services.production_files import parse_production_file
from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_animal,
    make_farm,
    make_user,
    one,
)

DAY = date(2026, 9, 10)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _enter(api, token, animal_id, measured_on=DAY, **values):
    return api.post(
        "/api/production",
        headers=auth(token),
        json={"animal_id": animal_id, "measured_on": measured_on.isoformat(), **values},
    )


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _import(api, token, content, path="/api/production/import", **fields):
    return api.post(
        path,
        headers=auth(token),
        data={"measured_on": DAY.isoformat(), **fields},
        files={"file": ("coleta.xlsx", content, "application/octet-stream")},
    )


def _active(cow: str) -> list:
    return one(
        "SELECT values->>'producao', values->>'manha', values->>'tarde', observacao "
        "FROM official_measurements WHERE animal_id = :a AND status = 'active'",
        a=cow,
    )


class TestMorningAndAfternoon:
    def test_total_is_the_sum_of_both_milkings(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _enter(api, operator, cow, manha=18, tarde=15.5)

        assert response.status_code == 201
        body = response.json()
        assert (body["producao"], body["manha"], body["tarde"]) == (33.5, 18, 15.5)
        assert _active(cow) == [("33.5", "18.0", "15.5", None)]

    def test_the_afternoon_completes_the_morning_without_a_correction(self, api, farm) -> None:
        """Quem lança a manhã cedo e a tarde à noite não está corrigindo nada."""
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        first = _enter(api, operator, cow, manha=18).json()

        response = _enter(api, operator, cow, manha=18, tarde=15)

        assert response.status_code == 201
        assert response.json()["supersedes"] == first["id"]
        assert _active(cow) == [("33.0", "18.0", "15.0", None)]
        audit = one(
            "SELECT action FROM audit_events WHERE entity_type = 'measurement' ORDER BY created_at"
        )
        assert audit == [("measurement_entered",), ("measurement_completed",)]

    def test_changing_a_milking_already_recorded_is_a_conflict(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _enter(api, operator, cow, manha=18)

        response = _enter(api, operator, cow, manha=20, tarde=15)

        assert response.status_code == 409
        assert response.json()["detail"]["existing"]["manha"] == 18
        assert _active(cow) == [("18.0", "18.0", None, None)]

    def test_sending_the_same_milkings_twice_is_harmless(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        first = _enter(api, operator, cow, manha=18, tarde=15)
        second = _enter(api, operator, cow, manha=18, tarde=15)

        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]

    def test_milkings_that_do_not_add_up_to_the_total_are_refused(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="695", name="RIO NEGRO", lote="LOTE 1")

        response = _enter(api, operator, cow, producao=29, manha=15.5, tarde=14)

        assert response.status_code == 422
        assert one("SELECT count(*) FROM official_measurements")[0][0] == 0

    def test_a_total_only_reading_is_completed_by_milkings_that_add_up(self, api, farm) -> None:
        """As leituras antigas têm só o total: manhã e tarde que somam o mesmo
        completam; que somam outra coisa, são conflito."""
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        other = make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        _enter(api, operator, cow, producao=25)
        _enter(api, operator, other, producao=25)

        assert _enter(api, operator, cow, manha=14, tarde=11).status_code == 201
        assert _enter(api, operator, other, manha=14, tarde=12).status_code == 409
        assert _active(cow) == [("25.0", "14.0", "11.0", None)]

    def test_more_than_the_plausible_in_one_day_is_refused(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        assert _enter(api, operator, cow, manha=50, tarde=40).status_code == 422

    def test_a_reading_needs_some_value(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        assert _enter(api, operator, cow, observacao="→ Seca").status_code == 422


class TestNote:
    def test_the_note_is_kept_with_the_reading(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        body = _enter(api, operator, cow, manha=4, tarde=3, observacao="  → Seca  ").json()

        assert body["observacao"] == "→ Seca"
        assert _active(cow) == [("7.0", "4.0", "3.0", "→ Seca")]

    def test_a_note_added_later_completes_the_reading(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _enter(api, operator, cow, manha=4, tarde=3)

        assert _enter(api, operator, cow, manha=4, tarde=3, observacao="→ Seca").status_code == 201
        assert _enter(api, operator, cow, manha=4, tarde=3, observacao="→ 3º Lote").status_code == 409
        assert _active(cow) == [("7.0", "4.0", "3.0", "→ Seca")]

    def test_reviewer_corrects_milkings_and_note(self, api, farm) -> None:
        _, operator = make_user("operator")
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        measurement = _enter(api, operator, cow, manha=18, tarde=15, observacao="→ Seca").json()

        response = api.post(
            f"/api/production/{measurement['id']}/correction",
            headers=auth(reviewer),
            json={"manha": 18, "tarde": 16, "reason": "tarde anotada errada"},
        )

        assert response.status_code == 201
        # Sem `observacao` no pedido, a anotação continua a mesma.
        assert _active(cow) == [("34.0", "18.0", "16.0", "→ Seca")]

    def test_a_correction_can_clear_the_note(self, api, farm) -> None:
        _, operator = make_user("operator")
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        measurement = _enter(api, operator, cow, manha=18, tarde=15, observacao="→ Seca").json()

        response = api.post(
            f"/api/production/{measurement['id']}/correction",
            headers=auth(reviewer),
            json={"manha": 18, "tarde": 15, "observacao": None, "reason": "vaca errada"},
        )

        assert response.status_code == 201
        assert _active(cow) == [("33.0", "18.0", "15.0", None)]


class TestSheet:
    def test_the_sheet_brings_milkings_note_and_the_previous_weighing(self, api, farm) -> None:
        _, operator = make_user("operator")
        agata = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        nova = make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        _enter(api, operator, agata, measured_on=date(2026, 7, 22), producao=30)
        _enter(api, operator, agata, measured_on=date(2026, 8, 25), manha=20, tarde=17.5)
        _enter(api, operator, agata, manha=19, tarde=16, observacao="→ 2º Lote")

        body = api.get(
            "/api/production/sheet",
            headers=auth(operator),
            params={"measured_on": DAY.isoformat(), "lote": "LOTE 1"},
        ).json()

        items = {item["brinco"]: item for item in body["items"]}
        agata_item = items["389"]
        assert (agata_item["producao"], agata_item["manha"], agata_item["tarde"]) == (35, 19, 16)
        assert agata_item["observacao"] == "→ 2º Lote"
        assert agata_item["anterior"] == {"measured_on": "2026-08-25", "producao": 37.5}
        assert items["027"]["anterior"] is None
        assert nova  # sem pesagem nenhuma


class TestSpreadsheetOfTheFarm:
    ROWS = [
        ["Pesagem do Leite – 25/08/2026 | 1º, 2º e 3º Lote"],
        ["Seq.", "Lote", "Nº Vaca", "Nome da Vaca", "Manhã (L)", "Tarde (L)", "Total (L)", "Observação"],
        ["  ── 1º Lote ──"],
        [1, "1º Lote", "548", "PRINCESA", 20, 17.5, 37.5, None],
        [2, "1º Lote", "695", "RIO NEGRO", 15.5, 14, 29, None],
        [3, "1º Lote", "853", "PRETINHA", 4, 3, None, "→ Seca"],
    ]

    def test_title_row_numero_da_vaca_milkings_and_note_are_read(self) -> None:
        parsed = parse_production_file(_xlsx(self.ROWS), "coleta.xlsx")

        rows = [(r.brinco_raw, r.manha, r.tarde, r.producao, r.observacao) for r in parsed.rows]
        assert rows == [
            ("548", 20, 17.5, 37.5, None),
            ("853", 4, 3, 7, "→ Seca"),
        ]
        # A seção "1º Lote" não é leitura; a RIO NEGRO é, mas não fecha.
        assert [(p.location, p.reason) for p in parsed.problems] == [
            ("linha 5", "manhã + tarde (29,5 L) não bate com o total (29 L)"),
        ]

    def test_importing_it_completes_a_total_only_reading(self, api, farm) -> None:
        _, operator = make_user("operator")
        princesa = make_animal(farm, brinco="548", name="PRINCESA", lote="LOTE 1")
        pretinha = make_animal(farm, brinco="853", name="PRETINHA", lote="LOTE 1")
        make_animal(farm, brinco="695", name="RIO NEGRO", lote="LOTE 1")
        _enter(api, operator, princesa, producao=37.5)

        preview = _import(api, operator, _xlsx(self.ROWS), path="/api/production/import/preview")
        statuses = {r["brinco_lido"]: r["status"] for r in preview.json()["rows"]}
        assert statuses == {"548": "complete", "853": "new"}

        response = _import(api, operator, _xlsx(self.ROWS), mode="new_only")

        assert response.status_code == 201, response.text
        assert response.json()["summary"]["completed"] == 1
        assert _active(princesa) == [("37.5", "20.0", "17.5", None)]
        assert _active(pretinha) == [("7.0", "4.0", "3.0", "→ Seca")]
