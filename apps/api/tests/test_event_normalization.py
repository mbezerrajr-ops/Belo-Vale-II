"""Normalização dos eventos lidos.

O leitor (visão, transcrição) entrega texto solto: "25/08", "ontem", "vendida",
"lote 2", "DEL 120". Aqui isso vira valor do domínio — ou fica vazio com um
alerta dizendo por quê. Nunca se inventa um valor para preencher lacuna.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.event_normalization import (
    normalize_event,
    parse_event_date,
)

REF = date(2026, 8, 25)


@pytest.fixture(autouse=True)
def _farm_today(monkeypatch):
    """Hoje fixo: os alertas de data (futura, antiga) não podem depender do
    dia em que a suíte roda."""
    monkeypatch.setattr("app.services.event_normalization.farm_today", lambda: date(2026, 9, 19))


def _codes(alerts) -> list[str]:
    return [alert["code"] for alert in alerts]


class TestDates:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("25/08/2026", date(2026, 8, 25)),
            ("25/08/26", date(2026, 8, 25)),
            ("2026-08-25", date(2026, 8, 25)),
            ("25-08-2026", date(2026, 8, 25)),
            ("25.08.2026", date(2026, 8, 25)),
            ("3/9/2026", date(2026, 9, 3)),
        ],
    )
    def test_full_dates(self, raw, expected) -> None:
        assert parse_event_date(raw, reference=REF) == expected

    def test_day_and_month_take_the_reference_year(self) -> None:
        assert parse_event_date("20/08", reference=REF) == date(2026, 8, 20)

    def test_day_and_month_after_the_reference_belong_to_last_year(self) -> None:
        """Em agosto, "parto em 15/12" só pode ser dezembro passado."""
        assert parse_event_date("15/12", reference=REF) == date(2025, 12, 15)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("hoje", REF), ("ontem", date(2026, 8, 24)), ("anteontem", date(2026, 8, 23))],
    )
    def test_spoken_relative_dates(self, raw, expected) -> None:
        assert parse_event_date(raw, reference=REF) == expected

    @pytest.mark.parametrize("raw", ["31/02/2026", "semana passada", "", None, "xx/yy"])
    def test_unreadable_or_impossible_dates(self, raw) -> None:
        assert parse_event_date(raw, reference=REF) is None


class TestProduction:
    def test_liters_with_comma_and_the_date_of_the_page(self) -> None:
        payload, alerts = normalize_event("production", {"producao": "21,5"}, reference_date=REF)

        assert payload == {"measured_on": "2026-08-25", "producao": 21.5}
        assert alerts == []

    def test_missing_liters_stays_empty_with_an_alert(self) -> None:
        payload, alerts = normalize_event("production", {"producao": "??"}, reference_date=REF)

        assert payload["producao"] is None
        assert "illegible_field" in _codes(alerts)

    def test_implausible_liters_are_kept_but_flagged(self) -> None:
        """215 L é quase certamente 21,5 mal lido. O valor fica para quem
        revisa ver; o alerta impede passar despercebido."""
        payload, alerts = normalize_event("production", {"producao": "215"}, reference_date=REF)

        assert payload["producao"] == 215.0
        assert "implausible_value" in _codes(alerts)

    def test_a_date_years_ago_is_flagged(self) -> None:
        """Na primeira folha real o modelo leu "25/08/2026" como 2024: as 18
        produções iriam para dois anos atrás. Data velha vira alerta."""
        payload, alerts = normalize_event(
            "production", {"producao": "7"}, reference_date=date(2024, 8, 25)
        )

        assert payload["measured_on"] == "2024-08-25"
        [alert] = [a for a in alerts if a["code"] == "old_date"]
        assert "25/08/2024" in alert["message"]

    def test_a_recent_date_is_not_flagged(self) -> None:
        _, alerts = normalize_event("production", {"producao": "7"}, reference_date=REF)

        assert alerts == []

    def test_without_any_date_the_field_is_empty(self) -> None:
        payload, alerts = normalize_event("production", {"producao": "20"}, reference_date=None)

        assert payload["measured_on"] is None
        assert "missing_field" in _codes(alerts)

    def test_the_two_milkings_that_add_up_raise_no_alert(self) -> None:
        """Folha de pesagem: "5,5 + 4 = 9,5" — manhã + tarde = total. Grava o
        total; as parcelas servem para conferir a leitura."""
        payload, alerts = normalize_event(
            "production", {"producao": "9,5", "parcelas": "5,5 + 4"}, reference_date=REF
        )

        assert payload == {"measured_on": "2026-08-25", "producao": 9.5}
        assert alerts == []

    def test_milkings_that_do_not_add_up_are_flagged(self) -> None:
        """4 + 3 = 9 não fecha: ou uma parcela ou o total foi mal lido."""
        payload, alerts = normalize_event(
            "production", {"producao": "9", "parcelas": "4 + 3"}, reference_date=REF
        )

        assert payload["producao"] == 9.0
        [alert] = [a for a in alerts if a["code"] == "sum_mismatch"]
        assert "4 + 3 = 7" in alert["message"]
        assert alert["field"] == "producao"

    def test_illegible_milkings_are_flagged(self) -> None:
        _, alerts = normalize_event(
            "production", {"producao": "7", "parcelas": "4 + ?"}, reference_date=REF
        )

        assert "sum_mismatch" in _codes(alerts)


class TestCalving:
    def test_calving_date(self) -> None:
        payload, alerts = normalize_event("calving", {"data": "10/08"}, reference_date=REF)

        assert payload == {"calved_on": "2026-08-10"}
        assert alerts == []

    def test_del_becomes_a_proposed_calving_date(self) -> None:
        """DEL não é dado primário: é calculado da data do parto. Um "DEL 120"
        dito no curral vira a data de parto correspondente, com aviso."""
        payload, alerts = normalize_event("calving", {"del": "120"}, reference_date=REF)

        assert payload == {"calved_on": "2026-04-27"}
        assert "derived_from_del" in _codes(alerts)
        assert "120" in alerts[0]["message"]

    def test_del_uses_its_own_date_when_given(self) -> None:
        payload, _ = normalize_event(
            "calving", {"del": "30", "data": "10/09/2026"}, reference_date=REF
        )

        assert payload == {"calved_on": "2026-08-11"}

    def test_future_calving_is_flagged(self) -> None:
        payload, alerts = normalize_event("calving", {"data": "30/12/2026"}, reference_date=REF)

        assert "future_date" in _codes(alerts)


class TestExit:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("vendida", "venda"),
            ("Venda", "venda"),
            ("vendeu pro vizinho", "venda"),
            ("morreu", "morte"),
            ("morte", "morte"),
            ("descarte", "descarte"),
            ("descartada", "descarte"),
            ("doação", "doacao"),
            ("doada", "doacao"),
        ],
    )
    def test_reason_words(self, raw, expected) -> None:
        payload, _ = normalize_event("exit", {"motivo": raw}, reference_date=REF)

        assert payload["reason"] == expected
        assert payload["exited_on"] == "2026-08-25"

    def test_unknown_reason_is_empty_with_an_alert(self) -> None:
        payload, alerts = normalize_event("exit", {"motivo": "sumiu"}, reference_date=REF)

        assert payload["reason"] is None
        assert "illegible_field" in _codes(alerts)

    def test_notes_are_kept(self) -> None:
        payload, _ = normalize_event(
            "exit", {"motivo": "venda", "observacao": "pro Zé do sítio"}, reference_date=REF
        )

        assert payload["notes"] == "pro Zé do sítio"


class TestLotChange:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("lote 2", "LOTE 2"), ("LOTE  3", "LOTE 3"), ("2", "LOTE 2"), ("engorda", "ENGORDA")],
    )
    def test_lot_names(self, raw, expected) -> None:
        payload, _ = normalize_event("lot_change", {"lote": raw}, reference_date=REF)

        assert payload == {"lote": expected, "valid_from": "2026-08-25"}


class TestDryOffAndNote:
    def test_dry_off_takes_the_date(self) -> None:
        payload, _ = normalize_event("dry_off", {"data": "ontem"}, reference_date=REF)

        assert payload == {"dried_on": "2026-08-24"}

    def test_dry_off_order_on_the_sheet_asks_to_confirm_the_date(self) -> None:
        """"→ SECAR" na folha é uma ordem: a data da folha é só um ponto de
        partida; quem revisa confirma quando a vaca foi de fato secada."""
        payload, alerts = normalize_event("dry_off", {"ordem": "secar"}, reference_date=REF)

        assert payload == {"dried_on": "2026-08-25"}
        assert _codes(alerts) == ["dry_off_order"]

    def test_note_keeps_the_text(self) -> None:
        payload, alerts = normalize_event(
            "note", {"texto": "  mancando da pata traseira  "}, reference_date=REF
        )

        assert payload == {"text": "mancando da pata traseira"}
        assert alerts == []

    def test_empty_note_is_flagged(self) -> None:
        payload, alerts = normalize_event("note", {"texto": " "}, reference_date=REF)

        assert payload == {"text": None}
        assert "missing_field" in _codes(alerts)


def test_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValueError):
        normalize_event("vacina", {}, reference_date=REF)
