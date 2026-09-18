"""Importação da coleta de leite por arquivo.

Regras decididas pelo titular (2026-09-18), e que estes testes fixam:

1. a primeira coluna ("Número" no sistema antigo) é o brinco, e a associação
   é só por ele — nome aparece apenas como aviso;
2. no modo "substituir", leitura diferente é substituída; a vaca que já tinha
   leitura na data e não está no arquivo novo **mantém** a leitura antiga;
3. "só leituras novas" é para qualquer conta; "substituir" é de revisor ou
   administrador, com motivo.

Nada é gravado na pré-visualização, e reenviar o mesmo arquivo não duplica.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook
from sqlalchemy.exc import DBAPIError

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

DAY = date(2026, 8, 25)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _csv(*lines: str) -> bytes:
    return ("Número;Nome;Produção\n" + "\n".join(lines) + "\n").encode("utf-8")


def _post(api, path, token, content, *, day=DAY, filename="coleta.csv", **fields):
    return api.post(
        path,
        headers=auth(token),
        data={"measured_on": day.isoformat(), **fields},
        files={"file": (filename, content, "application/octet-stream")},
    )


def _preview(api, token, content, **kwargs):
    return _post(api, "/api/production/import/preview", token, content, **kwargs)


def _commit(api, token, content, **kwargs):
    return _post(api, "/api/production/import", token, content, **kwargs)


def _baseline_reading(farm_id: str, animal_id: str, producao: float) -> str:
    baseline = one(
        "INSERT INTO baseline_imports (farm_id, source_path, source_sha256, "
        "animal_count, measurement_count, approved_by, approved_at) "
        "VALUES (:f, 'x', 'y', 1, 1, 'dono', now()) RETURNING id",
        f=farm_id,
    )[0][0]
    return str(
        one(
            "INSERT INTO official_measurements (animal_id, measured_on, values, status, "
            "provenance, baseline_import_id, reviewed_by) VALUES "
            "(:a, :d, CAST(:v AS jsonb), 'active', 'legacy_baseline', :b, 'dono') RETURNING id",
            a=animal_id,
            d=DAY,
            v=f'{{"producao": {producao}}}',
            b=baseline,
        )[0][0]
    )


def _by_brinco(body) -> dict[str, dict]:
    return {row["brinco_lido"]: row for row in body["rows"]}


class TestPreview:
    def test_each_line_gets_a_clear_status(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        same = make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        diff = make_animal(farm, brinco="B2-647", name="NEGUINHA", lote="LOTE 1")
        gone = make_animal(farm, brinco="700", name="VENDIDA", lote="LOTE 2")
        _baseline_reading(farm, same, 35)
        _baseline_reading(farm, diff, 34)
        one(
            "UPDATE animals SET exited_on = :d, exit_reason = 'venda' WHERE id = :a RETURNING id",
            d=DAY - timedelta(days=5),
            a=gone,
        )

        response = _preview(
            api,
            operator,
            _csv(
                "389;ÁGATA;21,5",
                "027;BORBOREMA;35",
                "B2-647;NEGUINHA;30",
                "999;DESCONHECIDA;20",
                "XXX;ILEGÍVEL;18",
                "700;VENDIDA;15",
                "389;ÁGATA;22",
            ),
        )

        assert response.status_code == 200
        rows = response.json()["rows"]
        statuses = [(r["brinco_lido"], r["status"]) for r in rows]
        assert statuses == [
            ("389", "duplicate"),
            ("027", "same"),
            ("B2-647", "different"),
            ("999", "not_found"),
            ("XXX", "no_brinco"),
            ("700", "exited"),
            ("389", "duplicate"),
        ]
        different = rows[2]
        assert different["existing_producao"] == 34
        assert different["producao"] == 30

    def test_association_is_only_by_brinco_and_name_is_a_warning(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        rows = _by_brinco(
            _preview(api, operator, _csv("389;CARMELITA;21,5")).json()
        )

        assert rows["389"]["status"] == "new"
        assert rows["389"]["animal_nome"] == "ÁGATA"
        assert any("CARMELITA" in note for note in rows["389"]["notes"])

    def test_a_name_never_finds_an_animal(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        rows = _by_brinco(_preview(api, operator, _csv("390;ÁGATA;21,5")).json())

        assert rows["390"]["status"] == "not_found"
        assert rows["390"]["animal_id"] is None

    def test_spreadsheet_that_dropped_the_leading_zero_gets_a_hint_not_a_guess(
        self, api, farm
    ) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        workbook = Workbook()
        workbook.active.append(["Brinco", "Nome", "Produção"])
        workbook.active.append([27, "BORBOREMA", 35])
        buffer = io.BytesIO()
        workbook.save(buffer)

        rows = _by_brinco(
            _preview(api, operator, buffer.getvalue(), filename="coleta.xlsx").json()
        )

        assert rows["27"]["status"] == "not_found"
        assert any("027" in note for note in rows["27"]["notes"])

    def test_implausible_values_are_flagged(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        rows = _by_brinco(_preview(api, operator, _csv("389;ÁGATA;215")).json())

        assert rows["389"]["status"] == "invalid"

    def test_preview_writes_nothing(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _preview(api, operator, _csv("389;ÁGATA;21,5"))

        assert one("SELECT count(*) FROM official_measurements")[0][0] == 0
        assert one("SELECT count(*) FROM production_imports")[0][0] == 0

    def test_replace_preview_lists_readings_that_will_be_kept(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        absent = make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        _baseline_reading(farm, absent, 35)

        body = _preview(api, reviewer, _csv("389;ÁGATA;21,5")).json()

        assert [(k["brinco"], k["producao"]) for k in body["kept"]] == [("027", 35)]

    def test_unreadable_lines_come_back_with_their_location(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        body = _preview(api, operator, _csv("389;ÁGATA;21,5", ";SEM BRINCO;18")).json()

        assert body["problems"] == [
            {"location": "linha 3", "text": " | SEM BRINCO | 18", "reason": "sem brinco"}
        ]

    def test_refused_file_explains_why(self, api, farm) -> None:
        _, operator = make_user("operator")

        response = _preview(api, operator, b"\xd0\xcf\x11\xe0" + b"\0" * 100, filename="x.xls")

        assert response.status_code == 422
        assert "xlsx" in response.json()["detail"]

    def test_future_date_is_refused(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _preview(
            api, operator, _csv("389;ÁGATA;21,5"), day=farm_today() + timedelta(days=1)
        )

        assert response.status_code == 422


class TestNewOnly:
    def test_creates_only_new_readings_and_keeps_the_file(self, api, farm) -> None:
        user_id, operator = make_user("operator")
        new = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        diff = make_animal(farm, brinco="B2-647", name="NEGUINHA", lote="LOTE 1")
        _baseline_reading(farm, diff, 34)
        content = _csv("389;ÁGATA;21,5", "B2-647;NEGUINHA;30")

        response = _commit(api, operator, content, mode="new_only")

        assert response.status_code == 201
        body = response.json()
        assert body["summary"]["created"] == 1
        assert body["summary"]["replaced"] == 0
        assert body["summary"]["skipped_different"] == 1
        readings = one(
            "SELECT animal_id::text, provenance, status, values->>'producao', reviewed_by "
            "FROM official_measurements ORDER BY created_at"
        )
        assert (new, "file_import", "active", "21.5", "operator@belovale") in readings
        assert (diff, "legacy_baseline", "active", "34", "dono") in readings
        stored = one(
            "SELECT content, imported_by_user_id::text, file_format FROM production_imports"
        )
        assert bytes(stored[0][0]) == content
        assert stored[0][1:] == (user_id, "csv")

    def test_imported_reading_reaches_the_dashboard(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _commit(api, operator, _csv("389;ÁGATA;21,5"), mode="new_only")

        painel = api.get(
            "/api/dashboard", headers=auth(operator), params={"measured_on": DAY.isoformat()}
        ).json()
        assert painel["total_production"] == 21.5

    def test_sending_the_same_file_again_changes_nothing(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        content = _csv("389;ÁGATA;21,5")

        first = _commit(api, operator, content, mode="new_only")
        second = _commit(api, operator, content, mode="new_only")

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["already_imported"] is True
        assert second.json()["id"] == first.json()["id"]
        assert one("SELECT count(*) FROM official_measurements")[0][0] == 1
        assert one("SELECT count(*) FROM production_imports")[0][0] == 1

    def test_nothing_to_import_is_not_recorded(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        _baseline_reading(farm, cow, 35)

        response = _commit(api, operator, _csv("027;BORBOREMA;35"), mode="new_only")

        assert response.status_code == 409
        assert one("SELECT count(*) FROM production_imports")[0][0] == 0

    def test_import_is_audited_without_the_file(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        _commit(api, operator, _csv("389;ÁGATA;21,5"), mode="new_only")

        audit = one(
            "SELECT action, actor, new_value->>'created', new_value ? 'content' "
            "FROM audit_events WHERE entity_type = 'production_import'"
        )
        assert audit == [("production_imported", "operator@belovale", "1", False)]


class TestReplace:
    def test_reviewer_replaces_a_collection_keeping_absent_cows(self, api, farm) -> None:
        """Os dados de 25/08: leitura diferente é substituída; a vaca que não
        está no arquivo novo mantém a leitura antiga."""
        _, reviewer = make_user("reviewer")
        diff = make_animal(farm, brinco="B2-647", name="NEGUINHA", lote="LOTE 1")
        same = make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        absent = make_animal(farm, brinco="700", name="AUSENTE", lote="LOTE 2")
        new = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        old_diff = _baseline_reading(farm, diff, 34)
        _baseline_reading(farm, same, 35)
        _baseline_reading(farm, absent, 12)

        response = _commit(
            api,
            reviewer,
            _csv("B2-647;NEGUINHA;30", "027;BORBOREMA;35", "389;ÁGATA;21,5"),
            mode="replace",
            reason="dados de 25/08 normalizados",
        )

        assert response.status_code == 201
        summary = response.json()["summary"]
        assert (summary["created"], summary["replaced"], summary["kept"]) == (1, 1, 1)
        active = dict(
            one(
                "SELECT animal_id::text, (values->>'producao')::numeric FROM official_measurements "
                "WHERE status = 'active'"
            )
        )
        assert active == {diff: 30, same: 35, absent: 12, new: 21.5}
        superseded = one(
            "SELECT m.id::text FROM official_measurements m WHERE status = 'superseded'"
        )
        assert superseded == [(old_diff,)]
        pointer = one(
            "SELECT supersedes_measurement_id::text FROM official_measurements "
            "WHERE animal_id = :a AND status = 'active'",
            a=diff,
        )
        assert pointer == [(old_diff,)]

    def test_operator_cannot_replace(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _commit(
            api, operator, _csv("389;ÁGATA;21,5"), mode="replace", reason="quero trocar"
        )

        assert response.status_code == 403

    def test_replace_needs_a_reason(self, api, farm) -> None:
        _, reviewer = make_user("reviewer")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")

        response = _commit(api, reviewer, _csv("389;ÁGATA;21,5"), mode="replace", reason=" ")

        assert response.status_code == 422


class TestHistory:
    def test_recent_imports_are_listed_without_the_file(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _commit(api, operator, _csv("389;ÁGATA;21,5"), mode="new_only", filename="julho.csv")

        body = api.get("/api/production/imports", headers=auth(operator)).json()

        assert [(i["filename"], i["measured_on"], i["imported_by"]) for i in body] == [
            ("julho.csv", DAY.isoformat(), "operator@belovale")
        ]
        assert "content" not in body[0]


class TestDatabaseGuards:
    def test_an_import_record_cannot_be_changed(self, api, farm) -> None:
        _, operator = make_user("operator")
        make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _commit(api, operator, _csv("389;ÁGATA;21,5"), mode="new_only")

        with pytest.raises(DBAPIError, match="immutable"):
            one("UPDATE production_imports SET filename = 'outro.csv' RETURNING id")

    def test_an_imported_reading_must_match_who_imported(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        make_animal(farm, brinco="027", name="BORBOREMA", lote="LOTE 1")
        _commit(api, operator, _csv("027;BORBOREMA;35"), mode="new_only")
        import_id = one("SELECT id FROM production_imports")[0][0]

        with pytest.raises(DBAPIError, match="production import"):
            one(
                "INSERT INTO official_measurements (animal_id, measured_on, values, status, "
                "provenance, production_import_id, reviewed_by) VALUES "
                "(:a, :d, '{}', 'active', 'file_import', :i, 'outro@belovale') RETURNING id",
                a=cow,
                d=DAY,
                i=import_id,
            )
