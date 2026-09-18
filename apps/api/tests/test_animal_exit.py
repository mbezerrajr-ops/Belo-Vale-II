"""Baixa de animal: venda, morte, descarte, doação.

Antes, "tirar" uma vaca do rebanho era editar o campo `status` à mão — sem
data, sem motivo, e a vaca continuava ocupando o lote e entrando nas contas do
painel. A baixa passa a ser um ato com data e motivo, que encerra a lotação e
tira o animal do rebanho, sem apagar nada do que ele produziu.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.production_entry import farm_today
from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_animal,
    make_farm,
    make_user,
    one,
)

EXIT_DAY = date(2026, 9, 12)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _exit(api, token, animal_id, *, exited_on=EXIT_DAY, reason="venda", notes=None):
    body = {"exited_on": exited_on.isoformat(), "reason": reason}
    if notes is not None:
        body["notes"] = notes
    return api.post(f"/api/animals/{animal_id}/exit", headers=auth(token), json=body)


class TestExit:
    def test_reviewer_registers_a_sale(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _exit(api, reviewer, cow, notes="vendida para o vizinho")

        assert response.status_code == 200
        body = response.json()
        assert body["exited_on"] == EXIT_DAY.isoformat()
        assert body["exit_reason"] == "venda"
        assert body["exit_notes"] == "vendida para o vizinho"
        assert body["status"] == "Inativo"
        assert body["lote_atual"] is None

    def test_the_lot_is_closed_on_the_exit_day_not_erased(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _exit(api, reviewer, cow)

        rows = one(
            "SELECT lote, valid_to FROM animal_lot_assignments WHERE animal_id = :a",
            a=cow,
        )
        assert rows == [("LOTE 1", EXIT_DAY)]

    def test_exit_is_audited(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _exit(api, reviewer, cow, reason="morte")

        rows = one(
            "SELECT action, actor, new_value->>'reason' FROM audit_events "
            "WHERE entity_id = :a",
            a=cow,
        )
        assert rows == [("animal_exited", "reviewer@belovale", "morte")]

    def test_operator_cannot_register_an_exit(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        assert _exit(api, operator, cow).status_code == 403

    def test_unknown_reason_is_refused(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA")

        assert _exit(api, reviewer, cow, reason="sumiu").status_code == 422

    def test_future_exit_is_refused(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA")

        response = _exit(api, reviewer, cow, exited_on=farm_today() + timedelta(days=1))

        assert response.status_code == 422

    def test_cannot_exit_twice(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA")
        _exit(api, reviewer, cow)

        response = _exit(api, reviewer, cow, exited_on=EXIT_DAY + timedelta(days=1))

        assert response.status_code == 409

    def test_exit_before_the_last_reading_is_refused(self, api, farm) -> None:
        """Uma vaca vendida dia 12 não pode ter produção no dia 15: ou a data
        da baixa está errada, ou a da leitura. O sistema não escolhe qual."""
        _, reviewer = make_user("reviewer")
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        api.post(
            "/api/production",
            headers=auth(operator),
            json={
                "animal_id": cow,
                "measured_on": (EXIT_DAY + timedelta(days=3)).isoformat(),
                "producao": 20,
            },
        )

        response = _exit(api, reviewer, cow)

        assert response.status_code == 409
        assert "produção" in response.json()["detail"]

    def test_exit_before_the_current_lot_started_is_refused(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(
            farm, brinco="389", name="ÁGATA", lote="LOTE 1", lot_since=EXIT_DAY
        )

        response = _exit(api, reviewer, cow, exited_on=EXIT_DAY - timedelta(days=1))

        assert response.status_code == 409

    def test_past_production_is_kept(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        api.post(
            "/api/production",
            headers=auth(operator),
            json={
                "animal_id": cow,
                "measured_on": (EXIT_DAY - timedelta(days=2)).isoformat(),
                "producao": 20,
            },
        )

        _exit(api, reviewer, cow)

        assert one(
            "SELECT status FROM official_measurements WHERE animal_id = :a", a=cow
        ) == [("active",)]


class TestAfterExit:
    def _gone(self, api, farm):
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        _exit(api, reviewer, cow)
        return reviewer, cow

    def test_the_herd_list_hides_it_by_default(self, api, farm) -> None:
        reviewer, _ = self._gone(api, farm)

        herd = api.get("/api/animals", headers=auth(reviewer)).json()
        gone = api.get(
            "/api/animals", headers=auth(reviewer), params={"rebanho": "baixados"}
        ).json()
        everyone = api.get(
            "/api/animals", headers=auth(reviewer), params={"rebanho": "todos"}
        ).json()

        assert [a["brinco"] for a in herd["items"]] == ["027"]
        assert [a["brinco"] for a in gone["items"]] == ["389"]
        assert everyone["total"] == 2

    def test_the_dashboard_no_longer_counts_it(self, api, farm) -> None:
        reviewer, _ = self._gone(api, farm)

        painel = api.get("/api/dashboard", headers=auth(reviewer)).json()

        assert painel["total_animals"] == 1

    def test_it_cannot_be_moved_to_a_lot(self, api, farm) -> None:
        reviewer, cow = self._gone(api, farm)

        response = api.post(
            f"/api/animals/{cow}/lote",
            headers=auth(reviewer),
            json={"lote": "LOTE 2", "valid_from": "2026-09-15"},
        )

        assert response.status_code == 409

    def test_its_status_cannot_be_flipped_back_by_a_plain_edit(self, api, farm) -> None:
        """Voltar ao rebanho é desfazer a baixa, com motivo — não editar um
        campo e deixar data e motivo da saída sem sentido."""
        reviewer, cow = self._gone(api, farm)

        response = api.patch(
            f"/api/animals/{cow}", headers=auth(reviewer), json={"status": "Ativo"}
        )

        assert response.status_code == 409


class TestUndo:
    def test_reviewer_undoes_an_exit_registered_by_mistake(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _exit(api, reviewer, cow)

        response = api.post(
            f"/api/animals/{cow}/exit/undo",
            headers=auth(reviewer),
            json={"reason": "baixa lançada na vaca errada"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["exited_on"] is None
        assert body["exit_reason"] is None
        assert body["status"] == "Ativo"
        audit = one(
            "SELECT previous_value->>'exit_reason', new_value->>'reason' "
            "FROM audit_events WHERE action = 'animal_exit_undone'"
        )
        assert audit == [("venda", "baixa lançada na vaca errada")]

    def test_undo_requires_an_exit(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA")

        response = api.post(
            f"/api/animals/{cow}/exit/undo",
            headers=auth(reviewer),
            json={"reason": "engano"},
        )

        assert response.status_code == 409

    def test_undo_requires_a_reason(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA")
        _exit(api, reviewer, cow)

        response = api.post(
            f"/api/animals/{cow}/exit/undo", headers=auth(reviewer), json={"reason": " "}
        )

        assert response.status_code == 422
