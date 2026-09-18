"""Leitura dos arquivos de coleta de leite: CSV, XLSX e PDF.

O arquivo vem de fora — de uma planilha feita no escritório, de um relatório
exportado — e é lido no servidor. Por isso estes testes cobrem dois lados:

- **o que a fazenda de fato manda**: separador `;` do Excel em português,
  vírgula decimal, acentos em Windows-1252, cabeçalho em qualquer ordem,
  brinco `B2- 008` com espaço, célula numérica que perdeu o zero à esquerda;
- **o que não pode passar**: arquivo grande demais, `.xls` antigo, PDF
  escaneado sem texto, planilha que se expande a gigabytes ao abrir, PDF com
  centenas de páginas.

Nenhuma fixture é arquivo real: todas são geradas aqui.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.services.production_files import (
    MAX_BYTES,
    MAX_PDF_PAGES,
    ProductionFileError,
    parse_number_br,
    parse_production_file,
)


def _pdf(pages: list[list[str]]) -> bytes:
    """PDF mínimo com texto real, uma linha por entrada, montado à mão."""
    objects: list[bytes] = []
    page_ids = []
    font_id = 3
    next_id = 4
    body: list[tuple[int, bytes]] = []
    for lines in pages:
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        stream = b"BT /F1 10 Tf 14 TL 40 800 Td\n"
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream += b"(" + escaped.encode("cp1252") + b") Tj T*\n"
        stream += b"ET"
        body.append(
            (content_id, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        )
        body.append(
            (
                page_id,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (font_id, content_id),
            )
        )
        page_ids.append(page_id)
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)),
        (
            font_id,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>",
        ),
        *body,
    ]
    objects.sort()
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for number, payload in objects:
        offsets[number] = out.tell()
        out.write(b"%d 0 obj\n" % number + payload + b"\nendobj\n")
    xref = out.tell()
    total = max(offsets) + 1
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % total)
    for number in range(1, total):
        out.write(b"%010d 00000 n \n" % offsets[number])
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, xref))
    return out.getvalue()


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _triples(parsed) -> list[tuple[str, str | None, float]]:
    return [(row.brinco_raw, row.nome, row.producao) for row in parsed.rows]


class TestNumbers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("21,5", 21.5),
            ("21.5", 21.5),
            ("21,5 L", 21.5),
            ("1.234,5", 1234.5),
            ("0", 0.0),
            (18, 18.0),
            (18.25, 18.25),
        ],
    )
    def test_brazilian_and_plain_numbers(self, raw, expected) -> None:
        assert parse_number_br(raw) == expected

    @pytest.mark.parametrize("raw", ["", "abc", None, "--"])
    def test_non_numbers(self, raw) -> None:
        assert parse_number_br(raw) is None


class TestCsv:
    def test_excel_in_portuguese_semicolon_comma_and_windows_accents(self) -> None:
        content = "Número;Nome;Produção total (L)\n389;ÁGATA;21,5\n027;BORBOREMA;35\n".encode(
            "cp1252"
        )

        parsed = parse_production_file(content, "coleta.csv")

        assert parsed.file_format == "csv"
        assert _triples(parsed) == [("389", "ÁGATA", 21.5), ("027", "BORBOREMA", 35.0)]
        assert parsed.problems == []

    def test_utf8_with_bom_comma_separated_and_quoted(self) -> None:
        content = '﻿brinco,nome,litros\n"B2-647","NEGUINHA","34.0"\n'.encode("utf-8")

        parsed = parse_production_file(content, "coleta.csv")

        assert _triples(parsed) == [("B2-647", "NEGUINHA", 34.0)]

    def test_columns_are_found_by_header_in_any_order(self) -> None:
        content = "Nome;Litros;Brinco\nÁGATA;21,5;389\n".encode("utf-8")

        parsed = parse_production_file(content, "coleta.csv")

        assert _triples(parsed) == [("389", "ÁGATA", 21.5)]

    def test_without_header_the_legacy_order_applies(self) -> None:
        content = b"389;AGATA;21,5\n027;BORBOREMA;35\n"

        parsed = parse_production_file(content, "coleta.csv")

        assert _triples(parsed) == [("389", "AGATA", 21.5), ("027", "BORBOREMA", 35.0)]

    def test_two_columns_mean_brinco_and_production(self) -> None:
        content = b"Brinco;Producao\n389;21,5\n"

        parsed = parse_production_file(content, "coleta.csv")

        assert _triples(parsed) == [("389", None, 21.5)]

    def test_unreadable_lines_are_reported_with_their_line_number(self) -> None:
        content = b"Brinco;Nome;Producao\n389;AGATA;21,5\n;SEM BRINCO;18\n027;BORBOREMA;muito\n"

        parsed = parse_production_file(content, "coleta.csv")

        assert _triples(parsed) == [("389", "AGATA", 21.5)]
        assert [(p.location, p.reason) for p in parsed.problems] == [
            ("linha 3", "sem brinco"),
            ("linha 4", "produção ilegível"),
        ]

    def test_blank_lines_are_ignored(self) -> None:
        content = b"Brinco;Producao\n\n389;21,5\n;;\n"

        parsed = parse_production_file(content, "coleta.csv")

        assert _triples(parsed) == [("389", None, 21.5)]
        assert parsed.problems == []


class TestXlsx:
    def test_reads_the_first_sheet_with_header(self) -> None:
        content = _xlsx([["Brinco", "Nome", "Produção"], ["389", "ÁGATA", 21.5], ["B2-647", "NEGUINHA", 34]])

        parsed = parse_production_file(content, "coleta.xlsx")

        assert parsed.file_format == "xlsx"
        assert _triples(parsed) == [("389", "ÁGATA", 21.5), ("B2-647", "NEGUINHA", 34.0)]

    def test_numeric_brinco_cells_are_flagged(self) -> None:
        """Célula numérica perde o zero à esquerda: `027` vira 27. O leitor não
        adivinha — só marca, para a associação poder avisar."""
        content = _xlsx([["Brinco", "Nome", "Produção"], [27, "BORBOREMA", 35], ["027", "OUTRA", 20]])

        parsed = parse_production_file(content, "coleta.xlsx")

        assert [(r.brinco_raw, r.brinco_from_number) for r in parsed.rows] == [
            ("27", True),
            ("027", False),
        ]

    def test_formula_without_calculated_value_is_reported(self) -> None:
        """Uma fórmula nunca é executada. Sem o valor já calculado pelo Excel,
        a linha é relatada, não inventada."""
        content = _xlsx([["Brinco", "Produção"], ["389", "=10+11.5"], ["027", 35]])

        parsed = parse_production_file(content, "coleta.xlsx")

        assert _triples(parsed) == [("027", None, 35.0)]
        assert [(p.location, p.reason) for p in parsed.problems] == [
            ("linha 2", "fórmula sem valor calculado")
        ]

    def test_a_zip_bomb_is_refused_before_opening(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
            archive.writestr("xl/worksheets/sheet1.xml", b"\0" * (80 * 1024 * 1024))

        with pytest.raises(ProductionFileError, match="grande demais"):
            parse_production_file(buffer.getvalue(), "coleta.xlsx")


class TestPdf:
    def test_reads_text_lines(self) -> None:
        content = _pdf(
            [["Coleta de leite", "Numero Nome Producao", "389 AGATA 21,5", "B2-647 NEGUINHA 34"]]
        )

        parsed = parse_production_file(content, "coleta.pdf")

        assert parsed.file_format == "pdf"
        assert _triples(parsed) == [("389", "AGATA", 21.5), ("B2-647", "NEGUINHA", 34.0)]

    def test_brinco_with_inner_space_and_suffix(self) -> None:
        content = _pdf([["B2- 008 FULANA DE TAL 12,5", "B1-016VD MIMOSA 10"]])

        parsed = parse_production_file(content, "coleta.pdf")

        assert _triples(parsed) == [("B2- 008", "FULANA DE TAL", 12.5), ("B1-016VD", "MIMOSA", 10.0)]

    def test_line_without_name(self) -> None:
        content = _pdf([["389 21,5"]])

        parsed = parse_production_file(content, "coleta.pdf")

        assert _triples(parsed) == [("389", None, 21.5)]

    def test_lines_with_digits_that_do_not_parse_are_reported(self) -> None:
        content = _pdf([["Coleta de 25/08/2026", "389 AGATA 21,5"]])

        parsed = parse_production_file(content, "coleta.pdf")

        assert _triples(parsed) == [("389", "AGATA", 21.5)]
        assert [p.text for p in parsed.problems] == ["Coleta de 25/08/2026"]

    def test_a_scanned_pdf_is_refused_with_a_clear_message(self) -> None:
        content = _pdf([[]])

        with pytest.raises(ProductionFileError, match="sem texto"):
            parse_production_file(content, "coleta.pdf")

    def test_too_many_pages_are_refused(self) -> None:
        content = _pdf([["389 AGATA 21,5"]] * (MAX_PDF_PAGES + 1))

        with pytest.raises(ProductionFileError, match="páginas"):
            parse_production_file(content, "coleta.pdf")


class TestRefusals:
    def test_file_too_large(self) -> None:
        with pytest.raises(ProductionFileError, match="5 MB"):
            parse_production_file(b"389;21,5\n" * (MAX_BYTES // 9 + 1), "coleta.csv")

    def test_empty_file(self) -> None:
        with pytest.raises(ProductionFileError, match="vazio"):
            parse_production_file(b"", "coleta.csv")

    def test_old_xls_format(self) -> None:
        content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 500

        with pytest.raises(ProductionFileError, match="xlsx"):
            parse_production_file(content, "coleta.xls")

    def test_format_comes_from_the_content_not_the_name(self) -> None:
        """Um PDF renomeado para .csv é lido como PDF; um executável renomeado
        para .xlsx é recusado."""
        pdf = _pdf([["389 AGATA 21,5"]])
        assert parse_production_file(pdf, "coleta.csv").file_format == "pdf"

        with pytest.raises(ProductionFileError, match="formato"):
            parse_production_file(b"MZ\x90\x00" + b"\x00\xff" * 200, "coleta.xlsx")

    def test_a_file_with_no_readings_is_refused(self) -> None:
        with pytest.raises(ProductionFileError, match="nenhuma leitura"):
            parse_production_file(b"Brinco;Nome;Producao\n", "coleta.csv")
