"""Histórico de produção de um animal.

O sistema antigo tinha o "histórico de leituras" na ficha da vaca. Aqui ele
volta com o que o banco já guarda e o antigo não tinha: de onde veio cada
leitura, quem lançou, e — para as que foram corrigidas, anuladas ou
substituídas — o motivo e a versão anterior. Nada some da lista: uma leitura
substituída continua visível, marcada como tal.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.pg_support import (  # noqa: F401 — fixtures
    api,
    auth,
    db,
    make_animal,
    make_farm,
    make_user,
    one,
)

JUL = date(2026, 7, 22)
AUG = date(2026, 8, 25)
SEP = date(2026, 9, 10)


@pytest.fixture()
def farm(db) -> str:
    return make_farm()


def _baseline(farm_id: str, animal_id: str, day: date, producao: float) -> str:
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
            d=day,
            v=f'{{"producao": {producao}}}',
            b=baseline,
        )[0][0]
    )


def _history(api, token, animal_id):
    return api.get(f"/api/animals/{animal_id}/production", headers=auth(token))


class TestHistory:
    def test_lists_every_reading_with_origin_and_who(self, api, farm) -> None:
        _, operator = make_user("operator")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _baseline(farm, cow, JUL, 20)
        api.post(
            "/api/production",
            headers=auth(operator),
            json={"animal_id": cow, "measured_on": SEP.isoformat(), "producao": 21.5},
        )

        response = _history(api, operator, cow)

        assert response.status_code == 200
        body = response.json()
        assert [(e["measured_on"], e["producao"], e["status"], e["provenance"], e["responsible"]) for e in body] == [
            (SEP.isoformat(), 21.5, "active", "manual_entry", "operator@belovale"),
            (JUL.isoformat(), 20, "active", "legacy_baseline", "dono"),
        ]

    def test_a_correction_shows_the_reason_and_keeps_the_old_value(self, api, farm) -> None:
        _, operator = make_user("operator")
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        first = api.post(
            "/api/production",
            headers=auth(operator),
            json={"animal_id": cow, "measured_on": SEP.isoformat(), "producao": 21.5},
        ).json()
        api.post(
            f"/api/production/{first['id']}/correction",
            headers=auth(reviewer),
            json={"producao": 12, "reason": "anotado errado no caderno"},
        )

        body = _history(api, operator, cow).json()

        assert [(e["producao"], e["status"], e["reason"]) for e in body] == [
            (12, "active", "anotado errado no caderno"),
            (21.5, "superseded", None),
        ]
        assert body[0]["supersedes"] == first["id"]

    def test_a_voided_reading_shows_why(self, api, farm) -> None:
        _, operator = make_user("operator")
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        entry = api.post(
            "/api/production",
            headers=auth(operator),
            json={"animal_id": cow, "measured_on": SEP.isoformat(), "producao": 21.5},
        ).json()
        api.post(
            f"/api/production/{entry['id']}/void",
            headers=auth(reviewer),
            json={"reason": "lançado na vaca errada"},
        )

        body = _history(api, operator, cow).json()

        assert [(e["status"], e["reason"]) for e in body] == [
            ("voided", "lançado na vaca errada")
        ]

    def test_an_imported_reading_names_the_file_and_the_replacement_reason(
        self, api, farm
    ) -> None:
        _, reviewer = make_user("reviewer")
        cow = make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
        _baseline(farm, cow, AUG, 34)
        api.post(
            "/api/production/import",
            headers=auth(reviewer),
            data={
                "measured_on": AUG.isoformat(),
                "mode": "replace",
                "reason": "dados de 25/08 normalizados",
            },
            files={"file": ("agosto.csv", b"Numero;Producao\n389;30\n", "text/csv")},
        )

        body = _history(api, reviewer, cow).json()

        assert [(e["provenance"], e["status"], e["source"], e["reason"]) for e in body] == [
            ("file_import", "active", "agosto.csv", "dados de 25/08 normalizados"),
            ("legacy_baseline", "superseded", None, None),
        ]

    def test_unknown_animal_is_404(self, api, farm) -> None:
        _, operator = make_user("operator")

        response = _history(api, operator, "00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404

    def test_requires_login(self, api, farm) -> None:
        cow = make_animal(farm, brinco="389", name="ÁGATA")

        assert api.get(f"/api/animals/{cow}/production").status_code == 401
