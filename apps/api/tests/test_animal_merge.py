"""Juntar duas fichas do mesmo animal.

A conferência de 25/08 achou vacas com duas fichas: uma com o brinco, outra
sem, cada uma com parte da produção (SAIA BRANCA, MEIAS BRANCA, BRANQUINHA).
A correção era anular e relançar, uma medição por vez. Juntar faz isso de uma
vez, com as mesmas regras:

- a ficha que fica é a que tem o brinco — é ele a identidade;
- nada se apaga: cada produção da ficha duplicada é relançada na que fica,
  apontando para a original, e a duplicada fica arquivada;
- nada se decide em silêncio: produção das duas no mesmo dia bloqueia, e quem
  junta resolve antes.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.farm_clock import farm_today
from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_animal,
    make_farm,
    make_user,
    one,
)
from tests.test_event_proposals import _event, _load

JULHO, AGOSTO = date(2026, 7, 22), date(2026, 8, 25)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


@pytest.fixture()
def revisor(farm):
    # Depois da fazenda: a limpeza do banco vem antes de criar a conta.
    return make_user("reviewer", "dono@belovale")[1]


def _producao(api, token, animal_id, litros, dia):
    resposta = api.post(
        "/api/production",
        headers=auth(token),
        json={"animal_id": animal_id, "measured_on": dia.isoformat(), "producao": litros},
    )
    assert resposta.status_code in (200, 201), resposta.text
    return resposta.json()["id"]


def _previa(api, token, animal_id, outra):
    return api.get(f"/api/animals/{animal_id}/merge", headers=auth(token), params={"other_id": outra})


def _juntar(api, token, animal_id, outra, motivo="a mesma vaca: ficha repetida na baseline"):
    return api.post(
        f"/api/animals/{animal_id}/merge",
        headers=auth(token),
        json={"other_id": outra, "reason": motivo},
    )


def _ativas(animal_id):
    return one(
        "SELECT measured_on, (values->>'producao')::float FROM official_measurements "
        "WHERE animal_id = :a AND status = 'active' ORDER BY measured_on",
        a=animal_id,
    )


@pytest.fixture()
def saia_branca(farm, api, revisor):
    """A vaca com brinco e a ficha duplicada sem brinco, cada uma com um dia."""
    certa = make_animal(farm, brinco="861", name="SAIA BRANCA")
    duplicada = make_animal(farm, brinco=None, name="SAIA BRANCA")
    _producao(api, revisor, certa, 18.0, AGOSTO)
    _producao(api, revisor, duplicada, 21.5, JULHO)
    return certa, duplicada


class TestTheDuplicateJoinsTheRightFicha:
    def test_the_production_moves_to_the_ficha_with_brinco(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        resposta = _juntar(api, revisor, duplicada, certa)

        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["id"] == certa
        assert _ativas(certa) == [(JULHO, 21.5), (AGOSTO, 18.0)]
        assert _ativas(duplicada) == []

    def test_nothing_is_erased_the_original_points_to_its_copy(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        _juntar(api, revisor, duplicada, certa)

        [(original, status)] = one(
            "SELECT id::text, status FROM official_measurements WHERE animal_id = :a", a=duplicada
        )
        assert status == "superseded"
        [(proveniencia, quem, aponta)] = one(
            "SELECT provenance, reviewed_by, supersedes_measurement_id::text FROM official_measurements "
            "WHERE animal_id = :a AND measured_on = :d AND status = 'active'",
            a=certa,
            d=JULHO,
        )
        assert (proveniencia, quem, aponta) == ("manual_entry", "dono@belovale", original)

    def test_the_duplicate_is_archived_out_of_the_herd(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        _juntar(api, revisor, duplicada, certa)

        ficha = api.get(f"/api/animals/{duplicada}", headers=auth(revisor)).json()
        assert ficha["merged_into_id"] == certa
        assert ficha["merged_at"] is not None
        busca = api.get("/api/animals", headers=auth(revisor), params={"name": "saia"}).json()
        assert [item["id"] for item in busca["items"]] == [certa]
        todos = api.get("/api/animals", headers=auth(revisor), params={"rebanho": "todos"}).json()
        assert duplicada not in [item["id"] for item in todos["items"]]

    def test_the_ficha_that_stays_lists_what_was_joined(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        _juntar(api, revisor, duplicada, certa)

        ficha = api.get(f"/api/animals/{certa}", headers=auth(revisor)).json()
        assert [f["id"] for f in ficha["fichas_juntadas"]] == [duplicada]

    def test_it_is_audited_on_both_fichas(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        _juntar(api, revisor, duplicada, certa, motivo="conferido no curral")

        acoes = one(
            "SELECT action, entity_id::text, new_value->>'reason' FROM audit_events "
            "WHERE action IN ('animal_merged', 'animal_absorbed') ORDER BY action"
        )
        assert acoes == [
            ("animal_absorbed", certa, "conferido no curral"),
            ("animal_merged", duplicada, "conferido no curral"),
        ]
        movidas = one("SELECT count(*) FROM audit_events WHERE action = 'measurement_moved'")
        assert movidas == [(1,)]


class TestWhichFichaStays:
    def test_from_either_side_the_ficha_with_brinco_stays(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        assert _previa(api, revisor, certa, duplicada).json()["keep"]["id"] == certa
        assert _previa(api, revisor, duplicada, certa).json()["keep"]["id"] == certa

    def test_without_brinco_the_ficha_you_are_on_stays(self, api, farm, revisor) -> None:
        uma = make_animal(farm, brinco=None, name="MULATA")
        outra = make_animal(farm, brinco=None, name="Mulata")

        assert _previa(api, revisor, uma, outra).json()["keep"]["id"] == uma

    def test_two_brincos_are_two_animals(self, api, farm, revisor) -> None:
        """Brinco é identidade. Se um deles está errado, tire-o antes — é um
        ato com evidência, que não cabe dentro de "juntar"."""
        uma = make_animal(farm, brinco="448", name="MEIAS BRANCA")
        outra = make_animal(farm, brinco="498", name="MEIAS BRANCA")

        previa = _previa(api, revisor, uma, outra).json()
        assert any("duas fichas têm brinco" in b for b in previa["blockers"])
        assert _juntar(api, revisor, uma, outra).status_code == 409


class TestNothingIsDecidedInSilence:
    def test_production_on_the_same_day_in_both_blocks(self, api, farm, revisor) -> None:
        certa = make_animal(farm, brinco="861", name="SAIA BRANCA")
        duplicada = make_animal(farm, brinco=None, name="SAIA BRANCA")
        _producao(api, revisor, certa, 18.0, JULHO)
        _producao(api, revisor, duplicada, 21.5, JULHO)

        previa = _previa(api, revisor, duplicada, certa).json()
        resposta = _juntar(api, revisor, duplicada, certa)

        assert previa["conflicts"] == [
            {"measured_on": JULHO.isoformat(), "keep": 18.0, "drop": 21.5}
        ]
        assert resposta.status_code == 409
        assert "22/07/2026" in resposta.json()["detail"]
        assert _ativas(duplicada) == [(JULHO, 21.5)]  # nada mudou

    def test_production_after_the_exit_of_the_ficha_that_stays_blocks(self, api, farm, revisor) -> None:
        certa = make_animal(farm, brinco="861", name="SAIA BRANCA")
        duplicada = make_animal(farm, brinco=None, name="SAIA BRANCA")
        _producao(api, revisor, duplicada, 21.5, AGOSTO)
        api.post(
            f"/api/animals/{certa}/exit",
            headers=auth(revisor),
            json={"exited_on": "2026-08-01", "reason": "venda"},
        )

        resposta = _juntar(api, revisor, duplicada, certa)

        assert resposta.status_code == 409
        assert "baixa" in resposta.json()["detail"]

    def test_a_reason_is_required(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        assert _juntar(api, revisor, duplicada, certa, motivo=" ").status_code == 422

    def test_the_preview_shows_what_will_happen(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca

        previa = _previa(api, revisor, duplicada, certa).json()

        assert (previa["keep"]["id"], previa["drop"]["id"]) == (certa, duplicada)
        assert previa["moves"] == [{"measured_on": JULHO.isoformat(), "producao": 21.5}]
        assert previa["blockers"] == []
        assert _ativas(duplicada) == [(JULHO, 21.5)]  # só olhou


class TestWhatTheDuplicateHadIsNotLost:
    def test_empty_fields_are_filled_and_filled_ones_kept(self, api, farm, revisor) -> None:
        certa = make_animal(farm, brinco="861", name="SAIA BRANCA")
        duplicada = make_animal(farm, brinco=None, name="Saia Branca")
        api.patch(
            f"/api/animals/{duplicada}",
            headers=auth(revisor),
            json={"nascimento": "2019-03-10", "observacoes": "chifre torto"},
        )

        previa = _previa(api, revisor, duplicada, certa).json()
        _juntar(api, revisor, duplicada, certa)

        assert previa["fills"] == {"nascimento": "2019-03-10", "observacoes": "chifre torto"}
        ficha = api.get(f"/api/animals/{certa}", headers=auth(revisor)).json()
        assert (ficha["name"], ficha["nascimento"], ficha["observacoes"]) == (
            "SAIA BRANCA",
            "2019-03-10",
            "chifre torto",
        )

    def test_the_lot_of_the_duplicate_goes_to_a_ficha_without_one(self, api, farm, revisor) -> None:
        certa = make_animal(farm, brinco="861", name="SAIA BRANCA")
        duplicada = make_animal(farm, brinco=None, name="SAIA BRANCA", lote="LOTE 1")

        _juntar(api, revisor, duplicada, certa)

        assert api.get(f"/api/animals/{certa}", headers=auth(revisor)).json()["lote_atual"] == "LOTE 1"
        [(fim,)] = one(
            "SELECT valid_to FROM animal_lot_assignments WHERE animal_id = :a", a=duplicada
        )
        assert fim == farm_today()

    def test_a_pending_proposal_follows_the_ficha_that_stays(self, api, farm, revisor) -> None:
        """O brinco estava na ficha errada: a leitura achou a duplicada; o
        brinco saiu dela, e as fichas foram juntadas."""
        certa = make_animal(farm, brinco="861", name="SAIA BRANCA")
        duplicada = make_animal(farm, brinco="999", name="SAIA BRANCA")
        [proposta] = _load(farm, "dono@belovale", _event("production", "999", "Saia Branca", producao="20"))
        api.request(
            "DELETE",
            f"/api/animals/{duplicada}/brinco",
            headers=auth(revisor),
            json={"evidence": "brinco lido na vaca errada"},
        )

        _juntar(api, revisor, duplicada, certa)

        [(candidata, versao)] = one(
            "SELECT candidate_animal_id::text, version FROM event_proposals WHERE id = :p", p=proposta
        )
        assert (candidata, versao) == (certa, 2)


class TestTheArchivedFichaDoesNotChange:
    @pytest.fixture()
    def juntadas(self, api, revisor, saia_branca):
        certa, duplicada = saia_branca
        assert _juntar(api, revisor, duplicada, certa).status_code == 200
        return certa, duplicada

    def test_it_cannot_be_edited(self, api, revisor, juntadas) -> None:
        _, duplicada = juntadas

        resposta = api.patch(f"/api/animals/{duplicada}", headers=auth(revisor), json={"name": "X"})

        assert resposta.status_code == 409
        assert "juntada" in resposta.json()["detail"]

    def test_it_receives_no_production(self, api, revisor, juntadas) -> None:
        _, duplicada = juntadas

        resposta = api.post(
            "/api/production",
            headers=auth(revisor),
            json={"animal_id": duplicada, "measured_on": (AGOSTO + timedelta(days=1)).isoformat(), "producao": 10},
        )

        assert resposta.status_code in (404, 409)
        assert "juntada" in resposta.text

    def test_it_is_not_joined_again(self, api, farm, revisor, juntadas) -> None:
        _, duplicada = juntadas
        terceira = make_animal(farm, brinco=None, name="Saia Branca II")

        assert _juntar(api, revisor, terceira, duplicada).status_code == 409


class TestTheArchivedFichaIsNotOffered:
    def test_the_review_suggests_only_the_ficha_that_stayed(self, api, farm, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca
        # Sem brinco lido: a caixa sugere pelo nome.
        _load(farm, "dono@belovale", _event("note", None, "Saia Branca", texto="mancando"))
        antes = api.get("/api/proposals", headers=auth(revisor), params={"status": "pending"}).json()
        assert {s["id"] for s in antes[0]["name_suggestions"]} == {certa, duplicada}

        _juntar(api, revisor, duplicada, certa)

        depois = api.get("/api/proposals", headers=auth(revisor), params={"status": "pending"}).json()
        assert [s["id"] for s in depois[0]["name_suggestions"]] == [certa]

    def test_approving_on_the_archived_ficha_is_refused(self, api, farm, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca
        [proposta] = _load(farm, "dono@belovale", _event("note", None, "Saia Branca", texto="mancando"))
        _juntar(api, revisor, duplicada, certa)

        resposta = api.post(
            f"/api/proposals/{proposta}/approve",
            headers=auth(revisor),
            json={"expected_version": 1, "animal_id": duplicada, "payload": {"text": "mancando"}},
        )

        assert resposta.status_code == 422
        assert "juntada" in resposta.json()["detail"]

    def test_the_dashboard_does_not_count_it(self, api, revisor, saia_branca) -> None:
        certa, duplicada = saia_branca
        antes = api.get("/api/dashboard", headers=auth(revisor)).json()["total_animals"]

        _juntar(api, revisor, duplicada, certa)

        assert api.get("/api/dashboard", headers=auth(revisor)).json()["total_animals"] == antes - 1


class TestWhoMayJoin:
    def test_an_operator_does_not_join(self, api, saia_branca) -> None:
        certa, duplicada = saia_branca
        _, operador = make_user("operator", "vaqueiro@belovale")

        assert _juntar(api, operador, duplicada, certa).status_code == 403
        assert _previa(api, operador, duplicada, certa).status_code == 403

    def test_a_ficha_of_nowhere_is_not_found(self, api, revisor, saia_branca) -> None:
        from uuid import uuid4

        certa, _ = saia_branca

        assert _previa(api, revisor, certa, str(uuid4())).status_code == 404
