"""Nota do leitor contra o gabarito.

Refinar o leitor (instrução, resolução, modelo) só vale com número: quantos
brincos, litros e anotações saíram certos em folhas reais já conferidas. As
folhas ficam fora do Git; aqui os testes usam gabaritos sintéticos.
"""

from __future__ import annotations

import json

from app.core.evaluate_reader import compare, main


def _line(seq, brinco, nome, manha, tarde, total, anotacao=None):
    return {
        "seq": seq, "brinco": brinco, "nome": nome, "manha": manha,
        "tarde": tarde, "total": total, "anotacao": anotacao, "trecho": "",
    }


TRUTH = {
    "data": "25/08/2026",
    "lote": "3º LOTE",
    "linhas": [
        _line("1", "853", "PRETINHA", "4", "3", "7"),
        _line("2", "694", "ANDORINHA", "3", "4", "7"),
        _line("3", "633", "GIGANTE", "2", "2", "4", "SECAR"),
    ],
}


class TestCompare:
    def test_a_perfect_reading_scores_everything(self) -> None:
        score = compare(TRUTH, TRUTH)

        assert score.lines_expected == 3
        assert score.missed == 0
        assert score.invented == 0
        assert score.header_date_ok
        assert all(score.correct[field] == 3 for field in ("brinco", "nome", "total", "anotacao"))

    def test_each_wrong_field_is_counted_where_it_happened(self) -> None:
        reading = {
            **TRUTH,
            "data": "25/08/2024",
            "linhas": [
                _line("1", "853", "PAETENHA", "4", "3", "7"),
                _line("2", "694", "ANDORINHA", "2", "4", "6"),
                _line("3", "638", "GIGANTE", "2", "2", "4", None),
            ],
        }

        score = compare(reading, TRUTH)

        assert not score.header_date_ok
        assert score.correct["brinco"] == 2
        assert score.correct["nome"] == 2
        assert score.correct["manha"] == 2
        assert score.correct["total"] == 2
        assert score.correct["anotacao"] == 2
        assert ("3", "brinco", "633", "638") in score.errors

    def test_numbers_are_compared_as_numbers(self) -> None:
        """"9,5" e "9.5" são o mesmo número; "016" e "16" não são o mesmo brinco."""
        truth = {**TRUTH, "linhas": [_line("1", "016", "BELMONTE", "5,5", "4", "9,5")]}
        reading = {**TRUTH, "linhas": [_line("1", "16", "BELMONTE", "5.5", "4", "9.5")]}

        score = compare(reading, truth)

        assert score.correct["total"] == 1
        assert score.correct["manha"] == 1
        assert score.correct["brinco"] == 0

    def test_names_ignore_accents_and_case(self) -> None:
        truth = {**TRUTH, "linhas": [_line("1", "389", "ÁGATA", "4", "5", "9")]}
        reading = {**TRUTH, "linhas": [_line("1", "389", "agata", "4", "5", "9")]}

        assert compare(reading, truth).correct["nome"] == 1

    def test_invented_and_missed_lines(self) -> None:
        """Linha inventada é o erro mais grave: dado que não existe na folha."""
        reading = {
            **TRUTH,
            "linhas": [TRUTH["linhas"][0], _line("9", "999", "FANTASMA", "1", "1", "2")],
        }

        score = compare(reading, TRUTH)

        assert score.invented == 1
        assert score.missed == 2


def test_the_command_reads_every_sample_with_a_gabarito(tmp_path, capsys) -> None:
    (tmp_path / "folha.pdf").write_bytes(b"%PDF-falso")
    (tmp_path / "folha.gabarito.json").write_text(json.dumps(TRUTH), encoding="utf-8")
    (tmp_path / "sem-gabarito.jpg").write_bytes(b"\xff\xd8\xff")

    def transcribe(content: bytes) -> dict:
        return TRUTH

    code = main(["--samples", str(tmp_path)], transcriber=transcribe)

    assert code == 0
    out = capsys.readouterr().out
    assert "folha.pdf" in out
    assert "sem-gabarito" not in out
    assert "brinco" in out and "3/3" in out
    saved = json.loads((tmp_path / "folha.leitura.json").read_text(encoding="utf-8"))
    assert saved["reference_date"] == "2026-08-25"
    assert len(saved["events"]) == 4  # 3 produções + 1 ordem de secagem
