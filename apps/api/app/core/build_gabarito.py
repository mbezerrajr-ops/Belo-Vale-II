"""Planilha conferida pelo titular → gabarito do leitor.

Uso::

    uv run python -m app.core.build_gabarito \\
        --xlsx "../../docs/Treinamento-VC/PLANILHA ATUALIZADA BELO VALE 25-08.xlsx" \\
        --para "../../docs/Treinamento-VC/Peso leite 25-08.pdf" --data 25/08/2026

A planilha tem uma linha por vaca, com lote, número, nome, ordenhas, total e
observação; é a leitura certa das fotos daquele dia. O gabarito sai ao lado da
foto (`<nome>.gabarito.json`) e serve ao `evaluate_reader`.

Duas diferenças entre a planilha e a folha:

- a planilha numera as linhas seguido, do começo ao fim; cada página da folha
  numera de 1 a N. O gabarito usa o número da página, com `pagina` para não
  confundir a linha 1 de cada lote;
- linhas em branco da folha aparecem na planilha marcadas como tal: elas
  ocupam um número, mas não são leitura.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

#: Cabeçalhos aceitos por campo, como `_fold` os deixa: sem acento, sem
#: espaços e em minúsculas ("Nº Vaca" → "novaca").
_COLUMNS = {
    "seq": ("seq.", "seq", "#"),
    "lote": ("lote",),
    "numero": ("novaca", "nvaca", "numero", "brinco"),
    "nome": ("nomedavaca", "nome"),
    "manha": ("manha(l)", "manha"),
    "tarde": ("tarde(l)", "tarde"),
    "total": ("totalanotado(l)", "totalanotado", "total"),
    "observacao": ("observacao", "obs"),
}

#: Número ilegível na folha, anotado assim pelo titular.
_NO_BRINCO = ("s/n", "sn", "")

#: Marca da linha que ficou em branco na folha.
_BLANK = "linha em branco"


class PlanilhaError(ValueError):
    """Planilha fora do formato esperado."""


def _fold(value: Any) -> str:
    text = "".join(str(value or "").split())
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _liters(value: Any) -> str | None:
    """Litros como a folha escreve: vírgula decimal, sem zero à toa."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return f"{value:g}".replace(".", ",")
    return _text(value)


def rows_to_gabarito(rows: list[dict[str, Any]], *, data: str) -> dict[str, Any]:
    """Linhas da planilha (uma por vaca) → gabarito no formato da transcrição."""
    pages: dict[str, int] = {}
    lines = []
    numbers: dict[str, int] = {}
    for row in rows:
        lote = _text(row.get("lote")) or "—"
        if "lote" not in _fold(lote):
            continue  # resumo ("TOTAL GERAL"), não é linha de folha
        page = pages.setdefault(lote, len(pages) + 1)
        numbers[lote] = numbers.get(lote, 0) + 1
        observacao = _text(row.get("observacao"))
        if observacao and _fold(observacao) == _fold(_BLANK):
            continue  # a linha existe na folha, mas está vazia
        numero = _text(row.get("numero"))
        brinco = None if numero is None or _fold(numero) in _NO_BRINCO else numero
        nome = _text(row.get("nome"))
        manha, tarde, total = (_liters(row.get(k)) for k in ("manha", "tarde", "total"))
        lines.append(
            {
                "pagina": page,
                "seq": str(numbers[lote]),
                "brinco": brinco,
                "nome": nome,
                "manha": manha,
                "tarde": tarde,
                "total": total,
                "anotacao": observacao,
                "trecho": " ".join(
                    part for part in (numero, nome, manha, tarde, total, observacao) if part
                ),
            }
        )
    return {
        "_origem": "planilha conferida pelo titular",
        "data": data,
        "lote": next(iter(pages), None),
        "linhas": lines,
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Lê a planilha e devolve as linhas de vaca, já com os campos nomeados."""
    from openpyxl import load_workbook

    book = load_workbook(path, data_only=True, read_only=True)
    for page in book:
        header_at = None
        indexes: dict[str, int] = {}
        for number, row in enumerate(page.iter_rows(values_only=True), start=1):
            folded = [_fold(cell) for cell in row]
            found = {
                field: folded.index(next(h for h in headers if h in folded))
                for field, headers in _COLUMNS.items()
                if any(h in folded for h in headers)
            }
            if {"lote", "nome", "total"} <= found.keys():
                header_at, indexes = number, found
                break
        if header_at is None:
            continue
        rows = []
        for row in page.iter_rows(min_row=header_at + 1, values_only=True):
            values = {field: row[index] for field, index in indexes.items() if index < len(row)}
            lote = _fold(values.get("lote"))
            if not isinstance(values.get("seq"), int) or "lote" not in lote:
                continue  # títulos, separadores e o "TOTAL GERAL" do fim
            rows.append(values)
        if rows:
            return rows
    raise PlanilhaError(
        "Não achei na planilha uma aba com as colunas Lote, Nome da Vaca e Total."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xlsx", required=True, type=Path, help="Planilha conferida.")
    parser.add_argument(
        "--para", required=True, type=Path, help="Foto ou PDF a que a planilha corresponde."
    )
    parser.add_argument("--data", required=True, help="Data escrita na folha (ex.: 25/08/2026).")
    args = parser.parse_args(argv)

    try:
        rows = read_rows(args.xlsx)
    except (PlanilhaError, OSError) as error:
        print(f"erro: {error}", file=sys.stderr)
        return 2

    gabarito = rows_to_gabarito(rows, data=args.data)
    destination = args.para.with_name(f"{args.para.stem}.gabarito.json")
    destination.write_text(
        json.dumps(gabarito, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages = len({line["pagina"] for line in gabarito["linhas"]})
    print(f"{len(gabarito['linhas'])} linhas em {pages} página(s) → {destination.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
