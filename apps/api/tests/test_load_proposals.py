"""Comando que carrega uma extração em JSON para a caixa de revisão.

Serve para demonstrar a caixa sem leitor real e para depurar os leitores das
próximas fases: a saída deles vai para um arquivo, o arquivo entra pela mesma
porta que eles usarão.
"""

from __future__ import annotations

import json

import pytest

from app.core.load_proposals import main
from tests.pg_support import db, make_animal, make_farm, make_user, one  # noqa: F401


def _write(tmp_path, data) -> str:
    path = tmp_path / "extracao.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_loads_the_events_as_pending_proposals(db, tmp_path) -> None:
    farm = make_farm()
    make_user("reviewer")
    make_animal(farm, brinco="389", name="ÁGATA", lote="LOTE 1")
    path = _write(
        tmp_path,
        {
            "reference_date": "2026-08-25",
            "events": [
                {"event_type": "production", "brinco": "389", "fields": {"producao": "21,5"}},
                {"event_type": "exit", "nome": "Mimosa", "fields": {"motivo": "vendida"}},
            ],
        },
    )

    code = main(["--email", "reviewer@belovale", "--file", path, "--label", "caderno 25/08"])

    assert code == 0
    assert one(
        "SELECT event_type, status FROM event_proposals ORDER BY position"
    ) == [("production", "pending"), ("exit", "pending")]
    assert one("SELECT kind, label FROM event_proposal_sources") == [("text", "caderno 25/08")]


def test_refuses_an_invalid_file_without_writing(db, tmp_path, capsys) -> None:
    make_farm()
    make_user("reviewer")
    path = _write(tmp_path, {"events": [{"event_type": "vacina", "fields": {}}]})

    code = main(["--email", "reviewer@belovale", "--file", path])

    assert code == 2
    assert "vacina" in capsys.readouterr().err
    assert one("SELECT count(*) FROM event_proposal_sources")[0][0] == 0


def test_refuses_an_unknown_account(db, tmp_path, capsys) -> None:
    make_farm()
    path = _write(tmp_path, {"events": []})

    assert main(["--email", "ninguem@belovale", "--file", path]) == 2
    assert "conta" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("kind", ["photo", "audio", "text"])
def test_accepts_the_three_source_kinds(db, tmp_path, kind) -> None:
    make_farm()
    make_user("reviewer")
    path = _write(tmp_path, {"events": [{"event_type": "note", "brinco": "1", "fields": {"texto": "x"}}]})

    assert main(["--email", "reviewer@belovale", "--file", path, "--kind", kind]) == 0
    assert one("SELECT kind FROM event_proposal_sources") == [(kind,)]
