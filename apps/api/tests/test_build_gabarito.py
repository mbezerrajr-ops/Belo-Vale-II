"""Planilha conferida pelo titular → gabarito do leitor.

Quando a coleta já foi digitada numa planilha ("PLANILHA ATUALIZADA BELO VALE
25-08.xlsx"), ela é a resposta certa para a foto correspondente: número, nome,
ordenhas, total e anotação de cada linha. Converter é melhor que transcrever à
mão — e o gabarito sai com 100+ linhas em vez de 18.
"""

from __future__ import annotations

import json

import openpyxl
import pytest

from app.core.build_gabarito import main, rows_to_gabarito


def _sheet(rows):
    return [
        {"seq": seq, "lote": lote, "numero": numero, "nome": nome,
         "manha": manha, "tarde": tarde, "total": total, "observacao": obs}
        for seq, lote, numero, nome, manha, tarde, total, obs in rows
    ]


LOTE_1 = [
    (1, "1º Lote", "S/N", "MOULA", 14, 11, 25, None),
    (2, "1º Lote", "518", "PRINCESA", 20, 17.5, 37.5, None),
    (3, "1º Lote", "859", "PUCONICA", 9, 7, 16, "→ 2º Lote"),
    (4, "1º Lote", None, None, None, None, None, "Linha em branco"),
]
LOTE_3 = [
    (5, "3º Lote", "853", "PRETINHA", 4, 3, 7, "→ Seca"),
    (6, "3º Lote", "016", "BELMONTE", 5.5, 4, 9.5, None),
]


class TestRowsToGabarito:
    def test_one_page_per_lote_with_the_row_numbers_of_the_sheet(self) -> None:
        """A folha numera as linhas de 1 a N em cada página; a planilha numera
        seguido, do começo ao fim. O gabarito usa o número da folha."""
        gabarito = rows_to_gabarito(_sheet(LOTE_1 + LOTE_3), data="25/08/2026")

        assert gabarito["data"] == "25/08/2026"
        assert [(line["pagina"], line["seq"], line["nome"]) for line in gabarito["linhas"]] == [
            (1, "1", "MOULA"),
            (1, "2", "PRINCESA"),
            (1, "3", "PUCONICA"),
            (2, "1", "PRETINHA"),
            (2, "2", "BELMONTE"),
        ]

    def test_a_blank_row_keeps_its_number_but_is_not_a_reading(self) -> None:
        rows = _sheet(LOTE_1 + [(5, "1º Lote", "462", "SABIA", 10, 5, 15, None)])

        gabarito = rows_to_gabarito(rows, data="25/08/2026")

        assert [line["seq"] for line in gabarito["linhas"]] == ["1", "2", "3", "5"]

    def test_liters_keep_the_comma_of_the_sheet(self) -> None:
        gabarito = rows_to_gabarito(_sheet(LOTE_3), data="25/08/2026")

        belmonte = gabarito["linhas"][1]
        assert (belmonte["manha"], belmonte["tarde"], belmonte["total"]) == ("5,5", "4", "9,5")

    def test_an_illegible_number_is_no_brinco(self) -> None:
        """"S/N" na planilha: o brinco não dava para ler na folha."""
        gabarito = rows_to_gabarito(_sheet(LOTE_1), data="25/08/2026")

        assert gabarito["linhas"][0]["brinco"] is None

    def test_the_annotation_is_kept_as_written(self) -> None:
        gabarito = rows_to_gabarito(_sheet(LOTE_1 + LOTE_3), data="25/08/2026")

        assert [line["anotacao"] for line in gabarito["linhas"]] == [
            None, None, "→ 2º Lote", "→ Seca", None
        ]

    def test_the_lote_of_the_first_page_is_the_header(self) -> None:
        gabarito = rows_to_gabarito(_sheet(LOTE_1), data="25/08/2026")

        assert gabarito["lote"] == "1º Lote"


    def test_the_total_row_of_the_sheet_is_not_a_page(self) -> None:
        """A planilha termina com "TOTAL GERAL": é resumo, não linha de folha."""
        rows = _sheet(LOTE_3 + [(7, "TOTAL GERAL", "-", "113 vacas", 1220.5, 1073.5, 2298.9, None)])

        gabarito = rows_to_gabarito(rows, data="25/08/2026")

        assert {line["pagina"] for line in gabarito["linhas"]} == {1}
        assert len(gabarito["linhas"]) == 2


def _write_xlsx(path, rows) -> None:
    book = openpyxl.Workbook()
    page = book.active
    page.title = "Dados Completos"
    page.append(["CONTROLE LEITEIRO – BELO VALE II"])
    page.append(["Pesagem do Leite – 25/08/2026 | 1º, 2º e 3º Lote"])
    page.append(
        ["Seq.", "Lote", "Nº Vaca", "Nome da Vaca", "Manhã (L)", "Tarde (L)",
         "Total Anotado (L)", "Total Calculado (L)", "Divergência?", "Observação"]
    )
    for seq, lote, numero, nome, manha, tarde, total, obs in rows:
        page.append([seq, lote, numero, nome, manha, tarde, total, total, None, obs])
    book.save(path)


def test_the_command_writes_the_gabarito_beside_the_photo(tmp_path, capsys) -> None:
    xlsx = tmp_path / "planilha.xlsx"
    _write_xlsx(xlsx, LOTE_1 + LOTE_3)
    photo = tmp_path / "Peso leite 25-08.pdf"
    photo.write_bytes(b"%PDF-falso")

    code = main(["--xlsx", str(xlsx), "--para", str(photo), "--data", "25/08/2026"])

    assert code == 0
    gabarito = json.loads((tmp_path / "Peso leite 25-08.gabarito.json").read_text(encoding="utf-8"))
    assert len(gabarito["linhas"]) == 5
    assert "5 linhas" in capsys.readouterr().out


def test_a_sheet_without_the_expected_columns_is_refused(tmp_path, capsys) -> None:
    book = openpyxl.Workbook()
    book.active.append(["outra coisa"])
    xlsx = tmp_path / "estranha.xlsx"
    book.save(xlsx)
    photo = tmp_path / "foto.jpeg"
    photo.write_bytes(b"\xff\xd8\xff")

    assert main(["--xlsx", str(xlsx), "--para", str(photo), "--data", "25/08/2026"]) == 2
    assert "coluna" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("raw", ["25/08/2026", "2026-08-25"])
def test_the_date_is_kept_as_given(tmp_path, raw) -> None:
    gabarito = rows_to_gabarito(_sheet(LOTE_3), data=raw)

    assert gabarito["data"] == raw
