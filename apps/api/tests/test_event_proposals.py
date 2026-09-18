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
from datetime import date

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
)

REF = date(2026, 8, 25)


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


def _load(farm_id: str, user_email: str, *events: ExtractedEvent, kind="text") -> list[str]:
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
                    extraction=EventExtraction(
                        events=list(events),
                        extractor_name="teste",
                        extractor_version="1",
                        reference_date=REF,
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
