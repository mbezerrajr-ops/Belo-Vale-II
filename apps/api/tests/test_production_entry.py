"""Lançamento manual de produção de leite.

Sem isto o sistema congela na última coleta importada: a única forma de uma
medição nascer era a revisão de OCR, e o provedor de OCR em uso é falso.

O que precisa valer, e o que estes testes garantem:

- o funcionário lança litro a litro, do celular, e cada lançamento fica salvo
  sozinho — uma queda de sinal no meio do curral não perde o que já foi feito;
- reenviar o mesmo valor (o botão apertado duas vezes, o retry do celular)
  não duplica nem dá erro;
- um valor *diferente* para a mesma vaca e data nunca sobrescreve em silêncio:
  vira conflito, e corrigir é um ato separado, com motivo e papel elevado;
- quem lançou fica gravado, e o próprio banco recusa um lançamento sem conta
  por trás.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from app.services.production_entry import MAX_LITERS, farm_today
from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    execute,
    make_animal,
    make_farm,
    make_user,
    one,
)

DAY = date(2026, 9, 10)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _enter(api, token, animal_id, producao, measured_on=DAY):
    return api.post(
        "/api/production",
        headers=auth(token),
        json={
            "animal_id": animal_id,
            "measured_on": measured_on.isoformat(),
            "producao": producao,
        },
    )


class TestEntry:
    def test_operator_records_a_reading(self, api, farm) -> None:
        user_id, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _enter(api, operator, cow, 21.5)

        assert response.status_code == 201
        body = response.json()
        assert body["producao"] == 21.5
        assert body["measured_on"] == DAY.isoformat()
        assert body["entered_by"] == "operator@belovale"

        row = one(
            "SELECT provenance, status, values->>'producao', reviewed_by, "
            "entered_by_user_id::text, lote_observado "
            "FROM official_measurements WHERE animal_id = :a",
            a=cow,
        )
        assert row == [
            ("manual_entry", "active", "21.5", "operator@belovale", user_id, "LOTE 1")
        ]

    def test_entry_is_audited(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _enter(api, operator, cow, 18)

        rows = one(
            "SELECT action, actor, new_value->>'producao' FROM audit_events "
            "WHERE entity_type = 'measurement'"
        )
        assert rows == [("measurement_entered", "operator@belovale", "18.0")]

    def test_the_new_reading_reaches_the_dashboard(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _enter(api, operator, cow, 24)

        painel = api.get(
            "/api/dashboard",
            headers=auth(operator),
            params={"measured_on": DAY.isoformat()},
        ).json()
        assert painel["total_production"] == 24


class TestRetryAndConflict:
    def test_sending_the_same_value_twice_is_harmless(self, api, farm) -> None:
        """O celular reenvia quando o sinal cai. Isso não pode virar erro nem
        linha duplicada."""
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        first = _enter(api, operator, cow, 21.5)
        second = _enter(api, operator, cow, 21.5)

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        assert one("SELECT count(*) FROM official_measurements")[0][0] == 1

    def test_a_different_value_never_overwrites_silently(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _enter(api, operator, cow, 21.5)

        response = _enter(api, operator, cow, 12)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["existing"]["producao"] == 21.5
        assert "correção" in detail["message"]
        values = one(
            "SELECT values->>'producao' FROM official_measurements "
            "WHERE status = 'active'"
        )
        assert values == [("21.5",)]

    def test_a_baseline_reading_also_blocks_a_blind_entry(self, api, farm) -> None:
        """A regra vale para qualquer origem: a baseline não é sobrescrita por
        um lançamento que nem sabia que ela existia."""
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        baseline = one(
            "INSERT INTO baseline_imports (farm_id, source_path, source_sha256, "
            "animal_count, measurement_count, approved_by, approved_at) "
            "VALUES (:f, 'x', 'y', 1, 1, 'dono', now()) RETURNING id",
            f=farm,
        )[0][0]
        one(
            "INSERT INTO official_measurements (animal_id, measured_on, values, "
            "status, provenance, baseline_import_id, reviewed_by) VALUES "
            "(:a, :d, '{\"producao\": 30}', 'active', 'legacy_baseline', :b, 'dono') "
            "RETURNING id",
            a=cow,
            d=DAY,
            b=baseline,
        )

        assert _enter(api, operator, cow, 12).status_code == 409


class TestValidation:
    @pytest.mark.parametrize("producao", [-1, MAX_LITERS + 0.1])
    def test_implausible_values_are_refused(self, api, farm, producao) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        assert _enter(api, operator, cow, producao).status_code == 422

    def test_zero_is_a_legitimate_reading(self, api, farm) -> None:
        """Vaca em tratamento tem o leite descartado: zero é dado, não erro."""
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        assert _enter(api, operator, cow, 0).status_code == 201

    def test_future_dates_are_refused(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _enter(api, operator, cow, 20, farm_today() + timedelta(days=1))

        assert response.status_code == 422
        assert "futur" in response.json()["detail"].lower()

    def test_unknown_animal_is_404(self, api, farm) -> None:
        _, operator = make_user("operator")

        response = _enter(api, operator, "00000000-0000-0000-0000-000000000000", 20)

        assert response.status_code == 404

    def test_an_animal_that_left_the_herd_cannot_receive_later_readings(
        self, api, farm
    ) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        one(
            "UPDATE animals SET exited_on = :d, exit_reason = 'venda', "
            "status = 'Inativo' WHERE id = :a RETURNING id",
            d=DAY - timedelta(days=1),
            a=cow,
        )

        response = _enter(api, operator, cow, 20)

        assert response.status_code == 409
        assert "baixa" in response.json()["detail"].lower()

    def test_anonymous_request_is_rejected(self, api, farm) -> None:
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = api.post(
            "/api/production",
            json={"animal_id": cow, "measured_on": DAY.isoformat(), "producao": 20},
        )

        assert response.status_code == 401


class TestCorrection:
    def _entered(self, api, farm, producao=21.5):
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        measurement_id = _enter(api, operator, cow, producao).json()["id"]
        return operator, cow, measurement_id

    def test_reviewer_corrects_with_a_reason(self, api, farm) -> None:
        _, _, measurement_id = self._entered(api, farm)
        _, reviewer = make_user("reviewer")

        response = api.post(
            f"/api/production/{measurement_id}/correction",
            headers=auth(reviewer),
            json={"producao": 12.5, "reason": "anotado errado no caderno"},
        )

        assert response.status_code == 201
        new = response.json()
        assert new["producao"] == 12.5
        assert new["supersedes"] == measurement_id
        rows = one(
            "SELECT status, values->>'producao' FROM official_measurements "
            "ORDER BY created_at"
        )
        assert rows == [("superseded", "21.5"), ("active", "12.5")]
        audit = one(
            "SELECT previous_value->>'producao', new_value->>'producao', "
            "new_value->>'reason' FROM audit_events "
            "WHERE action = 'measurement_corrected'"
        )
        assert audit == [("21.5", "12.5", "anotado errado no caderno")]

    def test_operator_cannot_correct(self, api, farm) -> None:
        operator, _, measurement_id = self._entered(api, farm)

        response = api.post(
            f"/api/production/{measurement_id}/correction",
            headers=auth(operator),
            json={"producao": 12.5, "reason": "errei"},
        )

        assert response.status_code == 403

    def test_a_correction_needs_a_reason(self, api, farm) -> None:
        _, _, measurement_id = self._entered(api, farm)
        _, reviewer = make_user("reviewer")

        response = api.post(
            f"/api/production/{measurement_id}/correction",
            headers=auth(reviewer),
            json={"producao": 12.5, "reason": "  "},
        )

        assert response.status_code == 422

    def test_a_superseded_reading_cannot_be_corrected_again(self, api, farm) -> None:
        """Corrigir a versão antiga criaria duas ativas — o banco recusaria,
        mas a API deve dizer isso antes."""
        _, _, measurement_id = self._entered(api, farm)
        _, reviewer = make_user("reviewer")
        api.post(
            f"/api/production/{measurement_id}/correction",
            headers=auth(reviewer),
            json={"producao": 12.5, "reason": "anotado errado"},
        )

        response = api.post(
            f"/api/production/{measurement_id}/correction",
            headers=auth(reviewer),
            json={"producao": 13, "reason": "de novo"},
        )

        assert response.status_code == 409


class TestVoid:
    def test_reviewer_voids_a_reading_on_the_wrong_cow(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        measurement_id = _enter(api, operator, cow, 21.5).json()["id"]
        _, reviewer = make_user("reviewer")

        response = api.post(
            f"/api/production/{measurement_id}/void",
            headers=auth(reviewer),
            json={"reason": "lançado na vaca errada"},
        )

        assert response.status_code == 204
        assert one("SELECT status FROM official_measurements") == [("voided",)]
        # Anular libera a data: o lançamento certo pode ser feito.
        assert _enter(api, operator, cow, 19).status_code == 201

    def test_operator_cannot_void(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        measurement_id = _enter(api, operator, cow, 21.5).json()["id"]

        response = api.post(
            f"/api/production/{measurement_id}/void",
            headers=auth(operator),
            json={"reason": "errei"},
        )

        assert response.status_code == 403


class TestSheet:
    def test_sheet_lists_the_cows_of_a_milking_lot_with_their_readings(
        self, api, farm
    ) -> None:
        _, operator = make_user("operator")
        agata = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        make_animal(farm, brinco="500", name="OUTRA", lote="LOTE 2")
        make_animal(farm, brinco="700", name="SECA", lote="ENGORDA", kind="management")
        _enter(api, operator, agata, 21.5)

        response = api.get(
            "/api/production/sheet",
            headers=auth(operator),
            params={"measured_on": DAY.isoformat(), "lote": "LOTE 1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["lote"] == "LOTE 1"
        assert [(i["brinco"], i["producao"]) for i in body["items"]] == [
            ("027", None),
            ("389", 21.5),
        ]
        assert body["lotes"] == ["LOTE 1", "LOTE 2"]

    def test_sheet_leaves_out_animals_that_left_the_herd(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        one(
            "UPDATE animals SET exited_on = '2026-09-01', exit_reason = 'venda' "
            "WHERE id = :a RETURNING id",
            a=cow,
        )

        body = api.get(
            "/api/production/sheet",
            headers=auth(operator),
            params={"measured_on": DAY.isoformat(), "lote": "LOTE 1"},
        ).json()

        assert body["items"] == []


class TestDatabaseGuard:
    def test_the_database_refuses_a_manual_reading_without_a_real_user(
        self, farm
    ) -> None:
        """A regra não depende só da API: um INSERT direto com um responsável
        inventado é recusado pelo trigger."""
        cow = make_animal(farm, brinco="389", name="ÁGATA")
        user_id, _ = make_user("operator")

        with pytest.raises(DBAPIError, match="existing user"):
            one(
                "INSERT INTO official_measurements (animal_id, measured_on, values, "
                "status, provenance, entered_by_user_id, reviewed_by) VALUES "
                "(:a, :d, '{}', 'active', 'manual_entry', :u, 'alguem@inventado') "
                "RETURNING id",
                a=cow,
                d=DAY,
                u=user_id,
            )
