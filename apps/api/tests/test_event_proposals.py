"""Propostas de eventos e a caixa de revisão.

Um leitor (visão, transcrição — nas próximas fases) entrega eventos lidos;
cada um vira uma proposta. O que estes testes garantem:

- **só o brinco associa**: nome lido nunca escolhe o animal, só aparece como
  sugestão para quem revisa;
- **nada entra sem aprovação**, e aprovar usa as mesmas regras do resto do
  sistema (lançamento, baixa, lote, cadastro);
- **o que foi lido não muda**: correções ficam à parte, e uma proposta
  decidida é imutável no banco;
- **duas pessoas não aprovam a mesma proposta** ao mesmo tempo.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import User
from app.services.event_extraction import EventExtraction, ExtractedEvent
from app.services.event_proposals import create_proposals
from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    database_url,
    db,
    make_animal,
    make_farm,
    make_user,
    one,
    storage,
)

REF = date(2026, 8, 25)


@pytest.fixture(autouse=True)
def _farm_today(monkeypatch):
    """Hoje fixo: os alertas de data (futura, antiga) não podem depender do
    dia em que a suíte roda."""
    monkeypatch.setattr("app.services.event_normalization.farm_today", lambda: date(2026, 9, 19))


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _event(event_type, brinco=None, nome=None, **fields) -> ExtractedEvent:
    return ExtractedEvent(
        event_type=event_type,
        brinco=brinco,
        nome=nome,
        fields=fields,
        evidence={"text": f"{brinco or nome}: {fields}"},
        confidence={"brinco": 0.9},
    )


def _load(
    farm_id: str,
    user_email: str,
    *events: ExtractedEvent,
    kind="text",
    reference: date | None = REF,
    image_asset_id: str | None = None,
) -> list[str]:
    """Cria as propostas pelo serviço, como o leitor fará, e devolve os ids."""

    async def run():
        engine = create_async_engine(database_url(), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                user = await session.scalar(select(User).where(User.email == user_email))
                source = await create_proposals(
                    session,
                    farm_id=farm_id,
                    user=user,
                    kind=kind,
                    label="caderno de 25/08",
                    image_asset_id=UUID(image_asset_id) if image_asset_id else None,
                    extraction=EventExtraction(
                        events=list(events),
                        extractor_name="teste",
                        extractor_version="1",
                        reference_date=reference,
                    ),
                )
                await session.commit()
                return str(source.id)
        finally:
            await engine.dispose()

    source_id = asyncio.run(run())
    return [
        str(row[0])
        for row in one(
            "SELECT id FROM event_proposals WHERE source_id = :s ORDER BY position", s=source_id
        )
    ]


def _inbox(api, token, status="pending"):
    return api.get("/api/proposals", headers=auth(token), params={"status": status})


def _approve(api, token, proposal_id, animal_id, payload, version=1, **extra):
    return api.post(
        f"/api/proposals/{proposal_id}/approve",
        headers=auth(token),
        json={"expected_version": version, "animal_id": animal_id, "payload": payload, **extra},
    )


class TestCreation:
    def test_brinco_finds_the_animal_and_the_raw_reading_is_kept(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", "Ágata", producao="21,5"))

        row = one(
            "SELECT candidate_animal_id::text, payload, raw_fields, status FROM event_proposals "
            "WHERE id = :p",
            p=proposal,
        )[0]
        assert row[0] == cow
        assert row[1] == {"measured_on": "2026-08-25", "producao": 21.5}
        assert row[2]["producao"] == "21,5"
        assert row[3] == "pending"

    def test_a_name_never_picks_the_animal(self, api, farm) -> None:
        """"A Ágata deu 20 litros": o nome vira sugestão, nunca associação."""
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        [proposal] = _load(farm, "reviewer@belovale", _event("production", None, "agata", producao="20"))

        assert one("SELECT candidate_animal_id FROM event_proposals WHERE id = :p", p=proposal) == [(None,)]
        item = _inbox(api, reviewer).json()[0]
        assert item["candidate"] is None
        assert [s["id"] for s in item["name_suggestions"]] == [cow]
        assert any(a["code"] == "no_brinco" for a in item["alerts"])

    def test_unknown_brinco_is_flagged(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")

        _load(farm, "reviewer@belovale", _event("production", "999", None, producao="20"))

        item = _inbox(api, reviewer).json()[0]
        assert item["candidate"] is None
        assert any(a["code"] == "animal_not_found" for a in item["alerts"])

    def test_a_prefixed_brinco_is_suggested_but_never_associated(self, api, farm) -> None:
        """No caderno está "694"; no cadastro, "B2-694". Pode ser o mesmo
        animal — mas brinco é identidade: o sistema sugere, quem revisa
        confirma (decisão do titular, 19/09/2026)."""
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="B2-694", name="ANDORINHA", lote="LOTE 3")

        [proposal] = _load(farm, "reviewer@belovale", _event("production", "694", "Andorinha", producao="7"))

        assert one("SELECT candidate_animal_id FROM event_proposals WHERE id = :p", p=proposal) == [(None,)]
        item = _inbox(api, reviewer).json()[0]
        assert item["candidate"] is None
        assert [s["id"] for s in item["name_suggestions"]] == [cow]
        [alert] = [a for a in item["alerts"] if a["code"] == "brinco_variant"]
        assert "B2-694" in alert["message"]
        assert not any(a["code"] == "animal_not_found" for a in item["alerts"])

    def test_leading_zeros_also_find_the_prefixed_brinco(self, api, farm) -> None:
        """"011" no caderno, "B2-11" no cadastro (DOMINÓ)."""
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="B2-11", name="DOMINÓ", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "011", "Domino", producao="7"))

        item = _inbox(api, reviewer).json()[0]
        assert [s["id"] for s in item["name_suggestions"]] == [cow]
        assert any(a["code"] == "brinco_variant" for a in item["alerts"])

    def test_the_variant_whose_name_matches_comes_first(self, api, farm) -> None:
        """Dois cadastros com o mesmo número: o nome lido desempata a ordem
        das sugestões — e só a ordem."""
        _, reviewer = make_user("reviewer")
        other = make_animal(farm, brinco="B1-419", name="ESTRELA", lote="LOTE 1")
        cow = make_animal(farm, brinco="B2-419", name="VIAJANTE", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "419", "Viajante", producao="7"))

        item = _inbox(api, reviewer).json()[0]
        assert [s["id"] for s in item["name_suggestions"]][:2] == [cow, other]

    def test_an_exact_brinco_is_not_confused_with_a_variant(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        make_animal(farm, brinco="B2-389", name="OUTRA", lote="LOTE 2")

        _load(farm, "reviewer@belovale", _event("production", "389", "Ágata", producao="9"))

        item = _inbox(api, reviewer).json()[0]
        assert item["candidate"]["id"] == cow
        assert not any(a["code"] == "brinco_variant" for a in item["alerts"])

    def test_a_misread_name_still_suggests_the_right_cow(self, api, farm) -> None:
        """Primeira folha real: "162 SASIA" era "462 SABIÁ". O brinco lido não
        existe; o nome, mesmo torto, aponta a vaca — como sugestão."""
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="462", name="SABIÁ", lote="LOTE 3")
        make_animal(farm, brinco="900", name="SAFIRA", lote="LOTE 3")
        make_animal(farm, brinco="901", name="MIMOSA", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "162", "SASIA", producao="15"))

        item = _inbox(api, reviewer).json()[0]
        assert item["candidate"] is None
        assert [s["id"] for s in item["name_suggestions"]][0] == cow
        assert "MIMOSA" not in [s["name"] for s in item["name_suggestions"]]

    def test_a_brinco_one_digit_off_breaks_the_tie_between_similar_names(self, api, farm) -> None:
        """"619 NEODORDA": REDONDA e PANDORA se parecem igual com o nome
        lido; o brinco de REDONDA (B2-649) difere do lido em um dígito."""
        _, reviewer = make_user("reviewer")
        make_animal(farm, brinco="B2-417", name="PANDORA", lote="LOTE 3")
        cow = make_animal(farm, brinco="B2-649", name="REDONDA", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "619", "NEODORDA", producao="5"))

        item = _inbox(api, reviewer).json()[0]
        assert [s["id"] for s in item["name_suggestions"]][0] == cow

    def test_a_prefixed_brinco_with_another_name_does_not_jump_the_queue(self, api, farm) -> None:
        """Primeira folha real, linha 15: lido "619 NEODA", era REDONDA
        (B2-649). B2-619 existe, mas é a MARIPOZA — o nome lido a desmente.
        Nome meio parecido + brinco a um dígito são dois sinais fracos que,
        juntos, põem REDONDA na frente."""
        _, reviewer = make_user("reviewer")
        other = make_animal(farm, brinco="B2-619", name="MARIPOZA", lote="LOTE 3")
        cow = make_animal(farm, brinco="B2-649", name="REDONDA", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "619", "NEODA", producao="5"))

        item = _inbox(api, reviewer).json()[0]
        assert [s["id"] for s in item["name_suggestions"]][:2] == [cow, other]

    def test_a_misspelled_name_of_the_same_cow_is_not_a_mismatch(self, api, farm) -> None:
        """"853 PAETENHA" é a PRETINHA mal lida, não outra vaca: alertar
        divergência aqui só ensinaria o revisor a ignorar o alerta."""
        _, reviewer = make_user("reviewer")
        make_animal(farm, brinco="853", name="PRETINHA", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "853", "PAETENHA", producao="7"))

        item = _inbox(api, reviewer).json()[0]
        assert not any(a["code"] == "name_mismatch" for a in item["alerts"])

    def test_a_brinco_from_the_wrong_row_still_offers_the_cow_named_on_the_line(
        self, api, farm
    ) -> None:
        """Formulário de 22/07: o brinco da margem desceu uma linha, e a linha
        da SARIEMA veio com o 016 da BELMONTE. A associação continua pelo
        brinco (com alerta), mas a SARIEMA aparece como sugestão para trocar."""
        _, reviewer = make_user("reviewer")
        belmonte = make_animal(farm, brinco="B2-016", name="BELMONTE", lote="LOTE 2")
        sariema = make_animal(farm, brinco="447", name="SARIEMA", lote="LOTE 2")

        _load(farm, "reviewer@belovale", _event("production", "B2-016", "SARIEMA", producao="21"))

        item = _inbox(api, reviewer).json()[0]
        assert item["candidate"]["id"] == belmonte
        assert [s["id"] for s in item["name_suggestions"]] == [sariema]
        [alert] = [a for a in item["alerts"] if a["code"] == "name_mismatch"]
        assert "Trocar animal" in alert["message"]

    def test_a_different_name_on_the_brinco_is_a_mismatch(self, api, farm) -> None:
        """O brinco pode ter sido mal lido e cair noutra vaca: o nome é o
        segundo sinal que avisa."""
        _, reviewer = make_user("reviewer")
        make_animal(farm, brinco="853", name="PRETINHA", lote="LOTE 3")

        _load(farm, "reviewer@belovale", _event("production", "853", "MIMOSA", producao="7"))

        item = _inbox(api, reviewer).json()[0]
        assert any(a["code"] == "name_mismatch" for a in item["alerts"])

    def test_the_source_keeps_the_raw_output_and_is_immutable(self, api, farm) -> None:
        make_user("reviewer")
        _load(farm, "reviewer@belovale", _event("note", "389", None, texto="mancando"))

        raw = one("SELECT raw_output FROM event_proposal_sources")[0][0]
        assert raw["events"][0]["fields"] == {"texto": "mancando"}
        with pytest.raises(DBAPIError, match="immutable"):
            one("UPDATE event_proposal_sources SET label = 'outro' RETURNING id")


class TestInbox:
    def test_lists_pending_proposals_with_source_and_candidate(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_user("reviewer")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _load(
            farm,
            "reviewer@belovale",
            _event("production", "389", None, producao="21,5"),
            _event("calving", "389", None, data="10/08"),
        )

        body = _inbox(api, operator).json()

        assert [i["event_type"] for i in body] == ["production", "calving"]
        assert body[0]["source"]["label"] == "caderno de 25/08"
        assert body[0]["candidate"]["brinco"] == "389"
        assert body[0]["candidate"]["lote_atual"] == "LOTE 1"
        assert body[0]["version"] == 1

    def test_requires_login(self, api, farm) -> None:
        assert api.get("/api/proposals").status_code == 401


class TestApproveProduction:
    def test_creates_an_official_reading_traced_to_the_proposal(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", None, producao="21,5"))

        response = _approve(api, reviewer, proposal, cow, {"measured_on": "2026-08-25", "producao": 21.5})

        assert response.status_code == 200
        reading = one(
            "SELECT provenance, status, values->>'producao', event_proposal_id::text, reviewed_by "
            "FROM official_measurements"
        )
        assert reading == [("proposal_review", "active", "21.5", proposal, "reviewer@belovale")]
        decided = one("SELECT status, applied_animal_id::text FROM event_proposals WHERE id = :p", p=proposal)
        assert decided == [("approved", cow)]

    def test_a_correction_is_kept_apart_from_what_was_read(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", None, producao="215"))

        _approve(api, reviewer, proposal, cow, {"measured_on": "2026-08-25", "producao": 21.5})

        row = one(
            "SELECT raw_fields->>'producao', payload->>'producao', applied_payload->>'producao' "
            "FROM event_proposals WHERE id = :p",
            p=proposal,
        )
        assert row == [("215", "215.0", "21.5")]

    def test_the_reviewer_picks_the_animal_when_only_a_name_was_read(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("production", None, "Ágata", producao="20"))

        response = _approve(api, reviewer, proposal, cow, {"measured_on": "2026-08-25", "producao": 20})

        assert response.status_code == 200
        assert one("SELECT animal_id::text FROM official_measurements") == [(cow,)]

    def test_a_different_existing_reading_needs_a_reason_to_be_replaced(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        api.post(
            "/api/production",
            headers=auth(operator),
            json={"animal_id": cow, "measured_on": "2026-08-25", "producao": 30},
        )
        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", None, producao="21,5"))
        payload = {"measured_on": "2026-08-25", "producao": 21.5}

        blocked = _approve(api, reviewer, proposal, cow, payload)
        replaced = _approve(api, reviewer, proposal, cow, payload, replace_reason="caderno confere")

        assert blocked.status_code == 409
        assert blocked.json()["detail"]["existing"]["producao"] == 30
        assert replaced.status_code == 200
        rows = one(
            "SELECT provenance, status, values->>'producao' FROM official_measurements ORDER BY created_at"
        )
        assert rows == [("manual_entry", "superseded", "30.0"), ("proposal_review", "active", "21.5")]

    def test_the_same_existing_reading_is_simply_confirmed(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        api.post(
            "/api/production",
            headers=auth(operator),
            json={"animal_id": cow, "measured_on": "2026-08-25", "producao": 21.5},
        )
        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", None, producao="21,5"))

        response = _approve(api, reviewer, proposal, cow, {"measured_on": "2026-08-25", "producao": 21.5})

        assert response.status_code == 200
        assert response.json()["result"]["already_recorded"] is True
        assert one("SELECT count(*) FROM official_measurements")[0][0] == 1

    def test_an_incomplete_payload_is_refused_and_stays_pending(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", None, producao="??"))

        response = _approve(api, reviewer, proposal, cow, {"measured_on": "2026-08-25", "producao": None})

        assert response.status_code == 422
        assert one("SELECT status FROM event_proposals WHERE id = :p", p=proposal) == [("pending",)]


class TestApproveOtherEvents:
    def test_calving_sets_the_calving_date_and_lactation(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1", situacao="Seca")
        [proposal] = _load(farm, "reviewer@belovale", _event("calving", "389", None, data="10/08"))

        response = _approve(api, reviewer, proposal, cow, {"calved_on": "2026-08-10"})

        assert response.status_code == 200
        assert one("SELECT ultimo_parto::text, situacao FROM animals WHERE id = :a", a=cow) == [
            ("2026-08-10", "Em lactação")
        ]

    def test_dry_off_marks_the_cow_dry(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("dry_off", "389", None))

        _approve(api, reviewer, proposal, cow, {"dried_on": "2026-08-25"})

        assert one("SELECT situacao FROM animals WHERE id = :a", a=cow) == [("Seca",)]

    def test_exit_uses_the_same_rules_as_the_animal_page(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("exit", "389", None, motivo="vendida"))

        response = _approve(
            api, reviewer, proposal, cow, {"exited_on": "2026-08-25", "reason": "venda", "notes": None}
        )

        assert response.status_code == 200
        assert one("SELECT exited_on::text, exit_reason, status FROM animals WHERE id = :a", a=cow) == [
            ("2026-08-25", "venda", "Inativo")
        ]

    def test_a_rule_violation_keeps_the_proposal_pending(self, api, farm) -> None:
        """A baixa antes da entrada no lote atual é recusada pela regra do
        cadastro; a proposta não pode ficar aprovada pela metade."""
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1", lot_since=date(2026, 8, 20))
        [proposal] = _load(farm, "reviewer@belovale", _event("exit", "389", None, motivo="venda"))

        response = _approve(
            api, reviewer, proposal, cow, {"exited_on": "2026-08-10", "reason": "venda", "notes": None}
        )

        assert response.status_code == 409
        assert one("SELECT status FROM event_proposals WHERE id = :p", p=proposal) == [("pending",)]
        assert one("SELECT exited_on FROM animals WHERE id = :a", a=cow) == [(None,)]

    def test_lot_change(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("lot_change", "389", None, lote="lote 2"))

        _approve(api, reviewer, proposal, cow, {"lote": "LOTE 2", "valid_from": "2026-08-25"})

        assert one(
            "SELECT lote FROM animal_lot_assignments WHERE animal_id = :a AND valid_to IS NULL", a=cow
        ) == [("LOTE 2",)]

    def test_note_is_appended_to_the_animal_record(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        one("UPDATE animals SET observacoes = 'mansa' WHERE id = :a RETURNING id", a=cow)
        [proposal] = _load(farm, "reviewer@belovale", _event("note", "389", None, texto="mancando"))

        _approve(api, reviewer, proposal, cow, {"text": "mancando"})

        assert one("SELECT observacoes FROM animals WHERE id = :a", a=cow) == [
            ("mansa\n25/08/2026: mancando",)
        ]


class TestReject:
    def test_reviewer_rejects_with_a_reason(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        [proposal] = _load(farm, "reviewer@belovale", _event("note", "389", None, texto="rabisco"))

        response = api.post(
            f"/api/proposals/{proposal}/reject",
            headers=auth(reviewer),
            json={"expected_version": 1, "reason": "leitura de um rabisco"},
        )

        assert response.status_code == 200
        assert one("SELECT status, decision_reason FROM event_proposals WHERE id = :p", p=proposal) == [
            ("rejected", "leitura de um rabisco")
        ]
        assert _inbox(api, reviewer).json() == []
        assert len(_inbox(api, reviewer, status="rejected").json()) == 1

    def test_rejecting_needs_a_reason(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        [proposal] = _load(farm, "reviewer@belovale", _event("note", "389", None, texto="x"))

        response = api.post(
            f"/api/proposals/{proposal}/reject",
            headers=auth(reviewer),
            json={"expected_version": 1, "reason": " "},
        )

        assert response.status_code == 422


class TestGuards:
    def test_operator_cannot_decide(self, api, farm) -> None:
        make_user("reviewer")
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("dry_off", "389", None))

        assert _approve(api, operator, proposal, cow, {"dried_on": "2026-08-25"}).status_code == 403

    def test_a_stale_version_is_refused(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("dry_off", "389", None))

        response = _approve(api, reviewer, proposal, cow, {"dried_on": "2026-08-25"}, version=7)

        assert response.status_code == 409

    def test_a_decided_proposal_cannot_be_decided_again(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("dry_off", "389", None))
        _approve(api, reviewer, proposal, cow, {"dried_on": "2026-08-25"})

        again = _approve(api, reviewer, proposal, cow, {"dried_on": "2026-08-25"}, version=2)

        assert again.status_code == 409

    def test_the_database_keeps_decided_proposals_frozen(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("dry_off", "389", None))
        _approve(api, reviewer, proposal, cow, {"dried_on": "2026-08-25"})

        with pytest.raises(DBAPIError, match="immutable"):
            one("UPDATE event_proposals SET decision_reason = 'mudei' WHERE id = :p RETURNING id", p=proposal)

    def test_the_database_refuses_a_reading_without_an_approved_proposal(self, api, farm) -> None:
        make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("production", "389", None, producao="20"))

        with pytest.raises(DBAPIError, match="approved production proposal"):
            one(
                "INSERT INTO official_measurements (animal_id, measured_on, values, status, "
                "provenance, event_proposal_id, reviewed_by) VALUES "
                "(:a, '2026-08-25', '{}', 'active', 'proposal_review', :p, 'reviewer@belovale') "
                "RETURNING id",
                a=cow,
                p=proposal,
            )

    def test_approval_is_audited(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        [proposal] = _load(farm, "reviewer@belovale", _event("dry_off", "389", None))

        _approve(api, reviewer, proposal, cow, {"dried_on": "2026-08-25"})

        assert one(
            "SELECT action, actor FROM audit_events WHERE entity_type = 'event_proposal'"
        ) == [("proposal_approved", "reviewer@belovale")]


class TestRegistryDates:
    def test_editing_the_calving_date_on_the_animal_page_is_audited(self, api, farm) -> None:
        """Regressão: a auditoria do cadastro não serializava datas, e editar o
        último parto pela ficha do animal devolvia 500."""
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = api.patch(
            f"/api/animals/{cow}", headers=auth(reviewer), json={"ultimo_parto": "2026-08-10"}
        )

        assert response.status_code == 200
        assert one(
            "SELECT new_value->>'ultimo_parto' FROM audit_events WHERE action = 'animal_updated'"
        ) == [("2026-08-10",)]


def _redate(api, token, source_id, value):
    return api.post(
        f"/api/proposals/sources/{source_id}/date", headers=auth(token), json={"reference_date": value}
    )


class TestSourceDate:
    """Trocar a data de um arquivo inteiro de uma vez: o leitor errou o
    cabeçalho (25/08/2026 lido como 2024) e as 18 produções vieram com a data
    errada. Corrigir uma a uma não é trabalho de gente."""

    def _sheet(self, farm):
        make_animal(farm, brinco="853", name="PRETINHA", lote="LOTE 3")
        make_animal(farm, brinco="B2-694", name="ANDORINHA", lote="LOTE 3")
        ids = _load(
            farm,
            "reviewer@belovale",
            _event("production", "853", "PRETINHA", producao="7"),
            _event("production", "694", "ANDORINHA", producao="7"),
            _event("calving", "853", None, **{"del": "10"}),
            _event("production", "853", None, producao="6", data="20/08/2024"),
            reference=date(2024, 8, 25),
        )
        source = one("SELECT id::text FROM event_proposal_sources")[0][0]
        return ids, source

    def test_moves_every_pending_proposal_to_the_new_date(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        ids, source = self._sheet(farm)

        response = _redate(api, reviewer, source, "2026-08-25")

        assert response.status_code == 200
        assert response.json() == {"updated": 4, "kept_decided": 0}
        rows = one(
            "SELECT payload, alerts, version FROM event_proposals ORDER BY position"
        )
        assert rows[0][0] == {"measured_on": "2026-08-25", "producao": 7.0}
        assert rows[0][2] == 2
        assert not any(a["code"] == "old_date" for a in rows[0][1])
        # DEL conta a partir da nova data.
        assert rows[2][0] == {"calved_on": "2026-08-15"}

    def test_keeps_what_identifies_the_animal(self, api, farm) -> None:
        """O alerta de brinco com prefixo não depende da data: continua."""
        _, reviewer = make_user("reviewer")
        _, source = self._sheet(farm)

        _redate(api, reviewer, source, "2026-08-25")

        alerts = one("SELECT alerts FROM event_proposals WHERE position = 2")[0][0]
        assert [a["code"] for a in alerts] == ["brinco_variant"]

    def test_a_date_written_on_the_line_is_not_overwritten(self, api, farm) -> None:
        """Só muda o que veio do cabeçalho; data escrita na linha é da linha."""
        _, reviewer = make_user("reviewer")
        _, source = self._sheet(farm)

        _redate(api, reviewer, source, "2026-08-25")

        payload = one("SELECT payload FROM event_proposals WHERE position = 4")[0][0]
        assert payload["measured_on"] == "2024-08-20"

    def test_decided_proposals_stay_as_they_were(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        ids, source = self._sheet(farm)
        rejected = api.post(
            f"/api/proposals/{ids[0]}/reject",
            headers=auth(reviewer),
            json={"expected_version": 1, "reason": "linha repetida"},
        )
        assert rejected.status_code == 200

        response = _redate(api, reviewer, source, "2026-08-25")

        assert response.json() == {"updated": 3, "kept_decided": 1}
        assert one("SELECT payload->>'measured_on' FROM event_proposals WHERE position = 1") == [
            ("2024-08-25",)
        ]

    def test_the_read_date_is_kept_and_the_correction_is_signed(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _, source = self._sheet(farm)

        _redate(api, reviewer, source, "2026-08-25")

        item = _inbox(api, reviewer).json()[0]
        assert item["source"]["reference_date"] == "2026-08-25"
        assert item["source"]["reference_date_read"] == "2024-08-25"
        assert item["source"]["corrected_by"] == "reviewer@belovale"
        assert one(
            "SELECT previous_value->>'reference_date', new_value->>'reference_date' "
            "FROM audit_events WHERE action = 'source_date_corrected'"
        ) == [("2024-08-25", "2026-08-25")]

    def test_a_reviewer_holding_the_old_version_is_refused(self, api, farm) -> None:
        """Quem estava com o cartão aberto antes da troca não aprova a data velha."""
        _, reviewer = make_user("reviewer")
        ids, source = self._sheet(farm)
        animal = one("SELECT id::text FROM animals WHERE brinco = '853'")[0][0]
        _redate(api, reviewer, source, "2026-08-25")

        response = _approve(
            api, reviewer, ids[0], animal, {"measured_on": "2024-08-25", "producao": 7}, version=1
        )

        assert response.status_code == 409

    def test_a_future_date_is_refused(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _, source = self._sheet(farm)

        assert _redate(api, reviewer, source, "2099-01-01").status_code == 422

    def test_an_operator_cannot_change_the_date(self, api, farm) -> None:
        make_user("reviewer")
        _, operator = make_user("operator")
        _, source = self._sheet(farm)

        assert _redate(api, operator, source, "2026-08-25").status_code == 403

    def test_an_unknown_source_is_not_found(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")

        response = _redate(api, reviewer, "00000000-0000-0000-0000-000000000000", "2026-08-25")

        assert response.status_code == 404

    def test_the_database_accepts_only_the_date_correction(self, api, farm) -> None:
        """O resto da fonte continua imutável, e a correção não se apaga."""
        _, reviewer = make_user("reviewer")
        _, source = self._sheet(farm)
        _redate(api, reviewer, source, "2026-08-25")

        with pytest.raises(DBAPIError, match="immutable"):
            one("UPDATE event_proposal_sources SET reference_date = '2026-08-25' RETURNING id")
        with pytest.raises(DBAPIError, match="cannot be erased"):
            one(
                "UPDATE event_proposal_sources SET corrected_reference_date = NULL, "
                "corrected_by_user_id = NULL, corrected_at = NULL RETURNING id"
            )


class TestPhotoInTheInbox:
    """Quem revisa vê a folha ao lado do que foi lido, sem trocar de tela."""

    def test_a_proposal_from_a_photo_carries_a_link_to_it(self, api, farm, storage) -> None:
        _, reviewer = make_user("reviewer")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        image_id = one(
            "INSERT INTO image_assets (farm_id, sha256, object_key, media_type, byte_size) "
            "VALUES (CAST(:f AS uuid), :s, :k, 'image/jpeg', 10) RETURNING id::text",
            f=farm,
            s=f"sha-{uuid.uuid4().hex}",
            k="fazenda/foto.jpg",
        )[0][0]

        _load(
            farm,
            "reviewer@belovale",
            _event("production", "389", None, producao="20"),
            kind="photo",
            image_asset_id=image_id,
        )

        item = _inbox(api, reviewer).json()[0]
        assert item["source"]["photo_url"].startswith("memory://fazenda/foto.jpg")

    def test_a_reading_without_a_photo_has_no_link(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        _load(farm, "reviewer@belovale", _event("note", "389", None, texto="mancando"))

        item = _inbox(api, reviewer).json()[0]
        assert item["source"]["photo_url"] is None
