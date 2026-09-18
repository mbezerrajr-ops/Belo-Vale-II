"""Leitura dos arquivos de coleta de leite: CSV, XLSX e PDF.

Este módulo só *lê*: transforma bytes em linhas (brinco lido, nome, litros) e
problemas localizados ("linha 4: produção ilegível"). Não consulta o banco e
não decide nada — associar ao animal e gravar é trabalho de
`production_import.py`.

Três cuidados valem para os três formatos:

- **o formato vem do conteúdo, não da extensão**: um PDF renomeado para
  `.csv` é lido como PDF, e um executável renomeado para `.xlsx` é recusado;
- **nada é executado**: fórmulas de planilha não são calculadas, e sem o
  valor já calculado pelo Excel a linha é relatada, não inventada;
- **limites antes de abrir**: tamanho do arquivo, tamanho descompactado da
  planilha (contra arquivos que se expandem a gigabytes) e número de páginas
  do PDF.

A coluna de identificação é o brinco — o "Número" do sistema antigo. Ela é
entregue como foi lida; a normalização fica com `app/services/brinco.py`.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field

#: Tamanho máximo do arquivo enviado.
MAX_BYTES = 5 * 1024 * 1024

#: Tamanho máximo da planilha depois de descompactada. Um XLSX é um zip: um
#: arquivo de poucos KB pode se expandir a gigabytes ao abrir.
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

#: Páginas de PDF lidas no máximo. Uma coleta cabe em poucas.
MAX_PDF_PAGES = 50

#: Linhas de dados lidas no máximo. O rebanho tem cerca de 400 animais.
MAX_ROWS = 5000


class ProductionFileError(ValueError):
    """O arquivo inteiro foi recusado. A mensagem é para o usuário final."""


@dataclass(frozen=True)
class ParsedRow:
    location: str
    brinco_raw: str
    nome: str | None
    producao: float
    #: A célula do brinco era um número, não texto. Planilhas apagam o zero
    #: à esquerda de números (`027` vira 27), então a associação precisa
    #: saber disso para avisar em vez de adivinhar.
    brinco_from_number: bool = False


@dataclass(frozen=True)
class FileProblem:
    location: str
    text: str
    reason: str


@dataclass
class ParsedFile:
    file_format: str
    rows: list[ParsedRow] = field(default_factory=list)
    problems: list[FileProblem] = field(default_factory=list)


# ------------------------------------------------------------------ números


def parse_number_br(value: object) -> float | None:
    """`21,5`, `21.5`, `1.234,5`, `21,5 L` → float. Ilegível → ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value).strip())
    if not text or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


# ------------------------------------------------------------- cabeçalho


def _fold(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def _column_role(header: object) -> str | None:
    folded = _fold(header)
    if not folded:
        return None
    if any(key in folded for key in ("produc", "litro", "leite")) or folded.startswith("total"):
        return "producao"
    if "brinco" in folded or "numero" in folded or folded in {"n", "no", "n.", "nº", "n°", "num", "id"}:
        return "brinco"
    if "nome" in folded or folded in {"vaca", "animal"}:
        return "nome"
    return None


@dataclass(frozen=True)
class _Columns:
    brinco: int
    producao: int
    nome: int | None


def _columns_from_header(cells: list[object]) -> _Columns | None:
    """Colunas pelo cabeçalho, ou ``None`` se a linha não é um cabeçalho."""
    if any(parse_number_br(cell) is not None for cell in cells if str(cell or "").strip()):
        return None
    roles: dict[str, int] = {}
    for index, cell in enumerate(cells):
        role = _column_role(cell)
        if role and role not in roles:
            roles[role] = index
    if not roles:
        return None
    if "brinco" not in roles or "producao" not in roles:
        raise ProductionFileError(
            "O cabeçalho precisa ter uma coluna de brinco (ou número) e uma de "
            "produção (ou litros)."
        )
    return _Columns(brinco=roles["brinco"], producao=roles["producao"], nome=roles.get("nome"))


def _positional(width: int) -> _Columns:
    # A ordem do sistema antigo: número (brinco), nome, produção.
    if width >= 3:
        return _Columns(brinco=0, nome=1, producao=2)
    return _Columns(brinco=0, nome=None, producao=1)


def _cell(cells: list[object], index: int | None) -> object:
    if index is None or index >= len(cells):
        return None
    return cells[index]


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _rows_from_table(
    table: list[tuple[str, list[object], list[object] | None]],
    parsed: ParsedFile,
) -> None:
    """Cabeçalho, colunas e linhas, iguais para CSV e XLSX.

    Cada entrada de `table` é (local, células, fórmulas-ou-None).
    """
    data = [entry for entry in table if not all(_blank(c) for c in entry[1])]
    if not data:
        return
    columns = _columns_from_header(data[0][1])
    if columns is None:
        columns = _positional(max(len(cells) for _, cells, _ in data))
    else:
        data = data[1:]

    for location, cells, formulas in data[:MAX_ROWS]:
        text = " | ".join("" if _blank(c) else str(c) for c in cells)
        brinco_cell = _cell(cells, columns.brinco)
        producao_cell = _cell(cells, columns.producao)
        if _blank(brinco_cell):
            parsed.problems.append(FileProblem(location, text, "sem brinco"))
            continue
        if _blank(producao_cell):
            formula = _cell(formulas, columns.producao) if formulas else None
            if isinstance(formula, str) and formula.startswith("="):
                parsed.problems.append(FileProblem(location, text, "fórmula sem valor calculado"))
            else:
                parsed.problems.append(FileProblem(location, text, "sem produção"))
            continue
        producao = parse_number_br(producao_cell)
        if producao is None:
            parsed.problems.append(FileProblem(location, text, "produção ilegível"))
            continue

        from_number = isinstance(brinco_cell, (int, float)) and not isinstance(brinco_cell, bool)
        if from_number and float(brinco_cell).is_integer():
            brinco_raw = str(int(brinco_cell))
        else:
            brinco_raw = str(brinco_cell).strip()
        nome_cell = _cell(cells, columns.nome)
        parsed.rows.append(
            ParsedRow(
                location=location,
                brinco_raw=brinco_raw,
                nome=None if _blank(nome_cell) else str(nome_cell).strip(),
                producao=producao,
                brinco_from_number=from_number,
            )
        )
    if len(data) > MAX_ROWS:
        raise ProductionFileError(
            f"O arquivo tem mais de {MAX_ROWS} linhas. Envie só a coleta do dia."
        )


# ----------------------------------------------------------------------- CSV


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # O Excel em português salva CSV em Windows-1252.
        return content.decode("cp1252", errors="replace")


def _read_csv(content: bytes) -> ParsedFile:
    text = _decode(content)
    sample = "\n".join(text.splitlines()[:20])
    delimiter = max((";", ",", "\t"), key=lambda d: sample.count(d))
    if sample.count(delimiter) == 0:
        delimiter = ";"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    table = [(f"linha {reader.line_num}", list(row), None) for row in reader]
    parsed = ParsedFile(file_format="csv")
    _rows_from_table(table, parsed)
    return parsed


# ---------------------------------------------------------------------- XLSX


def _read_xlsx(content: bytes) -> ParsedFile:
    # Importado aqui: só quem envia planilha paga o custo do openpyxl.
    from openpyxl import load_workbook
    from openpyxl.xml import DEFUSEDXML

    if not DEFUSEDXML:
        # Sem defusedxml, um XML malicioso dentro da planilha poderia ler
        # arquivos do servidor ou travá-lo. Melhor recusar do que arriscar.
        raise ProductionFileError("Leitura de planilha indisponível neste servidor.")

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            expanded = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as error:
        raise ProductionFileError("Não foi possível abrir esta planilha.") from error
    if expanded > MAX_UNCOMPRESSED_BYTES:
        raise ProductionFileError(
            "A planilha ficaria grande demais ao abrir. Envie só a coleta do dia."
        )

    try:
        values = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        formulas = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        value_rows = list(values.worksheets[0].iter_rows(values_only=True, max_row=MAX_ROWS + 2))
        formula_rows = list(formulas.worksheets[0].iter_rows(values_only=True, max_row=MAX_ROWS + 2))
    except ProductionFileError:
        raise
    except Exception as error:  # noqa: BLE001 — qualquer falha do leitor vira recusa clara
        raise ProductionFileError("Não foi possível ler esta planilha.") from error

    table = [
        (f"linha {index + 1}", list(row), list(formula_rows[index]) if index < len(formula_rows) else None)
        for index, row in enumerate(value_rows)
    ]
    parsed = ParsedFile(file_format="xlsx")
    _rows_from_table(table, parsed)
    return parsed


# ----------------------------------------------------------------------- PDF

#: Brinco no começo da linha: `389`, `B2-647`, `B2- 008`, `B1-016VD`.
_PDF_LINE = re.compile(
    r"^(?P<brinco>B\d+\s*-\s*\d+[A-Z]{0,3}|\d+)"
    r"(?:\s+(?P<nome>.+?))?"
    r"\s+(?P<producao>\d+(?:[.,]\d+)*)\s*(?:L|l|litros)?$"
)


def _read_pdf(content: bytes) -> ParsedFile:
    import pdfplumber

    parsed = ParsedFile(file_format="pdf")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ProductionFileError(
                    f"O PDF tem {len(pdf.pages)} páginas; o limite é {MAX_PDF_PAGES}."
                )
            texts = [page.extract_text() or "" for page in pdf.pages]
    except ProductionFileError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ProductionFileError("Não foi possível ler este PDF.") from error

    if not any(text.strip() for text in texts):
        raise ProductionFileError(
            "O PDF está sem texto — provavelmente é uma foto ou digitalização. "
            "Envie a planilha (CSV ou XLSX) ou digite na tela de Produção."
        )

    for page_number, text in enumerate(texts, start=1):
        if not text.strip():
            parsed.problems.append(
                FileProblem(f"página {page_number}", "", "página sem texto")
            )
            continue
        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue
            location = f"página {page_number}, linha {line_number}"
            match = _PDF_LINE.match(line)
            if match is None:
                # Linha sem dígito é título ou cabeçalho. Com dígito, pode ser
                # uma leitura que não entendemos: mostramos, não descartamos.
                if re.search(r"\d", line):
                    parsed.problems.append(FileProblem(location, line, "linha não reconhecida"))
                continue
            producao = parse_number_br(match["producao"])
            if producao is None:
                parsed.problems.append(FileProblem(location, line, "produção ilegível"))
                continue
            parsed.rows.append(
                ParsedRow(
                    location=location,
                    brinco_raw=match["brinco"],
                    nome=match["nome"],
                    producao=producao,
                )
            )
    return parsed


# ------------------------------------------------------------------ entrada


def _detect_format(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return "xlsx"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        raise ProductionFileError(
            "Arquivo .xls antigo. Abra no Excel e salve como .xlsx ou .csv."
        )
    if b"\x00" in content[:4096]:
        raise ProductionFileError("formato não reconhecido. Envie CSV, XLSX ou PDF.")
    return "csv"


def parse_production_file(content: bytes, filename: str) -> ParsedFile:
    """Lê o arquivo e devolve linhas e problemas. Recusa o arquivo inteiro com
    :class:`ProductionFileError` quando não há o que ler com segurança.

    `filename` só aparece em mensagens; o formato vem do conteúdo.
    """
    if not content:
        raise ProductionFileError("O arquivo está vazio.")
    if len(content) > MAX_BYTES:
        raise ProductionFileError("O arquivo passa de 5 MB. Envie só a coleta do dia.")

    file_format = _detect_format(content)
    if file_format == "pdf":
        parsed = _read_pdf(content)
    elif file_format == "xlsx":
        parsed = _read_xlsx(content)
    else:
        parsed = _read_csv(content)

    if not parsed.rows:
        raise ProductionFileError(
            f"Não encontrei nenhuma leitura em {filename}. O arquivo precisa ter "
            "brinco e produção em cada linha."
        )
    return parsed
