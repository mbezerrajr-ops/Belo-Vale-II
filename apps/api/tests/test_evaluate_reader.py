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


# ------------------------------------------------ contra o que já foi lançado

from app.core.evaluate_reader import compare_with_records  # noqa: E402

RECORDS = [
    {"brinco": "389", "nome": "ÁGATA", "total": 12.0},
    {"brinco": "B2-117", "nome": "AZEITONA", "total": 15.0},
    {"brinco": "497", "nome": "PONTA CURTA", "total": 11.0},
    {"brinco": "B2-694", "nome": "ANDORINHA", "total": 12.5},
]


class TestCompareWithRecords:
    """Folhas cujos dados já foram lançados: a verdade é o banco, sem
    transcrição à mão. Brinco, nome e total lidos contra o registro do dia."""

    def test_counts_brinco_total_and_name_against_the_records(self) -> None:
        lines = [
            _line("1", "389", "AGATA", "6", "6", "12"),
            _line("2", "117", "AZEITONA", "8", "7", "15"),  # sem prefixo: é a B2-117
            _line("13", "694", "ANDORINHA", "7,5", "5", "13"),  # total errado
        ]

        score = compare_with_records(lines, RECORDS)

        assert score.lines == 3
        assert score.brinco_found == 3
        assert score.total_ok == 2
        assert score.nome_ok == 3
        assert [r["nome"] for r in score.missing] == ["PONTA CURTA"]
        assert score.duplicated == []

    def test_a_brinco_pulled_from_the_neighbour_shows_up_twice(self) -> None:
        """Desalinhamento da margem: a linha sem brinco pega o de baixo, e o
        mesmo animal aparece em duas linhas."""
        lines = [
            _line("12", "694", "PONTA CURTA", "6", "5", "11"),
            _line("13", "694", "ANDORINHA", "7,5", "5", "12,5"),
        ]

        score = compare_with_records(lines, RECORDS)

        assert [r["nome"] for r in score.duplicated] == ["ANDORINHA"]
        assert score.nome_ok == 1

    def test_lines_without_a_record_are_listed(self) -> None:
        lines = [_line("3", "999", "FANTASMA", "1", "1", "2"), _line("4", None, "SEM BRINCO", "1", "1", "2")]

        score = compare_with_records(lines, RECORDS)

        assert score.brinco_found == 0
        assert [l["nome"] for l in score.unmatched] == ["FANTASMA", "SEM BRINCO"]


def test_the_command_scores_all_photos_of_a_date_against_the_records(tmp_path, capsys) -> None:
    (tmp_path / "lote1.jpeg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "lote3.jpeg").write_bytes(b"\xff\xd8\xff")
    pages = iter([
        {"data": "22/07/26", "lote": "1º", "linhas": [_line("1", "389", "AGATA", "6", "6", "12")]},
        {"data": "22/07/26", "lote": "3º", "linhas": [_line("1", "117", "AZEITONA", "8", "7", "15")]},
    ])

    code = main(
        ["--samples", str(tmp_path), "--records-date", "2026-07-22"],
        transcriber=lambda content: next(pages),
        records=RECORDS,
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "2 fotos" in out
    assert "brinco" in out and "2/4" in out
    assert (tmp_path / "lote1.transcricao.json").exists()


from types import SimpleNamespace  # noqa: E402

from app.core.evaluate_reader import review_reach  # noqa: E402


def _animal(brinco, name):
    return SimpleNamespace(id=f"a-{brinco}", brinco=brinco, name=name, exited_on=None)


HERD = [
    _animal("389", "ÁGATA"),
    _animal("B2-117", "AZEITONA"),
    _animal("497", "PONTA CURTA"),
    _animal("B2-694", "ANDORINHA"),
    _animal("B2-619", "MARIPOZA"),
]


class TestReviewReach:
    """O que o revisor vê: a vaca certa já associada ou em primeiro lugar nas
    sugestões — com as mesmas regras da caixa de Revisão."""

    def test_counts_the_cows_of_the_day_that_reach_the_review(self) -> None:
        lines = [
            _line("1", "389", "AGATA", "6", "6", "12"),  # associada pelo brinco
            _line("2", "117", "AZEITONA", "8", "7", "15"),  # sugestão B2-117
            _line("12", None, "PONTA CURTA", "6", "5", "11"),  # sugestão pelo nome
            _line("13", "691", "ANDORINHA", "7,5", "5", "12,5"),  # nome + 1 dígito
        ]

        reach = review_reach(lines, RECORDS, HERD)

        assert reach.reached == 4
        assert reach.repeated == 0
        assert reach.outside_day == 0

    def test_two_lines_on_the_same_cow_is_certainly_wrong(self) -> None:
        lines = [
            _line("1", "389", "AGATA", "6", "6", "12"),
            _line("2", "389", "AGATHA", "8", "7", "15"),
        ]

        reach = review_reach(lines, RECORDS, HERD)

        assert (reach.reached, reach.repeated) == (1, 1)

    def test_a_cow_without_a_record_that_day_is_counted_apart(self) -> None:
        """Pode ser erro de leitura — ou vaca cuja medição do dia está numa
        ficha duplicada sem brinco (achado em 22/07: SAIA BRANCA, TIETA...).
        Sem gabarito por linha, não dá para chamar de erro."""
        lines = [_line("1", "B2-619", "MARIPOZA", "6", "6", "12")]

        reach = review_reach(lines, RECORDS, HERD)

        assert (reach.reached, reach.repeated, reach.outside_day) == (0, 0, 1)


class TestReviewReachWithMismatchedName:
    def test_a_brinco_from_the_neighbour_row_is_fixed_with_one_tap(self) -> None:
        """Brinco da ÁGATA na linha da AZEITONA: a caixa associa pela brinco,
        avisa do nome divergente e oferece "Ou é esta: AZEITONA". Conta como
        alcançada, à parte, com um toque."""
        lines = [_line("2", "389", "AZEITONA", "8", "7", "15")]

        reach = review_reach(lines, RECORDS, HERD)

        assert (reach.reached, reach.one_tap) == (1, 1)
