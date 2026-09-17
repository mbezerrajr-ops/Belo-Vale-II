from __future__ import annotations

"""Import the animal report without coupling domain logic to PDF I/O."""

import argparse
import collections
import copy
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from build_platform_state import (
    atomic_write_text,
    encode_json,
    load_json_object,
    require_valid,
)
from state_contract import find_del_situation_warnings, repair_animal_ids


COLS = (
    (0, 120, "brinco"),
    (120, 300, "nome"),
    (300, 450, "lote"),
    (450, 545, "data"),
    (545, 900, "delx"),
)

LOTE_MAP = {
    "Lote 1": "LOTE 1",
    "Lote 2": "LOTE 2",
    "Lote 3": "LOTE 3",
    "Pré-Parto": "PRÉ-PARTO",
    "PIQUETES / REPASSE": "PIQUETES / REPASSE",
    "ENGORDA": "ENGORDA",
    "ENGENHO": "ENGENHO",
    "INSERLEITE": "INSERLEITE",
    "BEZERREIRO": "BEZERREIRO",
    "CAJARANAS": "CAJARANAS",
    "PALMA": "PALMA",
    "COLEGIO": "COLÉGIO",
    "ABREU": "ABREU",
}


def read_pdf_rows(path: Path) -> list[dict[str, str]]:
    import pdfplumber

    rows: list[dict[str, str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            by_line: dict[int, list[dict[str, Any]]] = collections.defaultdict(
                list
            )
            for word in page.extract_words():
                by_line[round(word["top"])].append(word)
            for top in sorted(by_line):
                words = sorted(by_line[top], key=lambda word: word["x0"])
                row = {
                    name: " ".join(
                        word["text"]
                        for word in words
                        if start <= word["x0"] < end
                    ).strip()
                    for start, end, name in COLS
                }
                tag = row["brinco"]
                if (
                    not tag
                    or tag == "Brinco"
                    or tag.startswith(("Fazenda", "FORMUL", "Total"))
                ):
                    continue
                rows.append(row)
    return rows


def normalize(value: str | None) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", (value or "").upper())
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"\s+", " ", normalized).strip()


def numeric_key(value: str | None) -> int | None:
    match = re.match(r"^(?:B\d+-)?0*(\d+)\b", str(value or "").strip())
    return int(match.group(1)) if match else None


def iso_date(value: str) -> str:
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", value):
        return ""
    day, month, year = value.split("/")
    return f"{year}-{month}-{day}"


@dataclass(frozen=True)
class MatchResult:
    matched_pairs: tuple[tuple[int, int], ...]
    ambiguities: tuple[tuple[str, str, tuple[str, ...]], ...]
    divergences: tuple[tuple[str, str, str, str], ...]

    @property
    def matched_count(self) -> int:
        return len(self.matched_pairs)


@dataclass(frozen=True)
class ImportResult:
    state: dict[str, Any]
    match: MatchResult
    row_count: int
    base_count_before: int
    new_animal_count: int
    lot_change_count: int
    calving_change_count: int
    changes: tuple[tuple[str, str, str, str, str], ...]
    legacy_only: tuple[tuple[str, str, str, str, int], ...]


def match_report_rows(
    state: Mapping[str, Any], rows: Sequence[Mapping[str, str]]
) -> MatchResult:
    animals = list(state.get("vacas", []))
    by_number: dict[int, list[int]] = collections.defaultdict(list)
    by_name: dict[str, list[int]] = collections.defaultdict(list)
    for index, animal in enumerate(animals):
        number = numeric_key(animal.get("numero"))
        if number is not None:
            by_number[number].append(index)
        by_name[normalize(animal.get("nome"))].append(index)

    used: set[int] = set()
    matches: dict[int, int] = {}
    ambiguities: list[tuple[str, str, tuple[str, ...]]] = []
    divergences: list[tuple[str, str, str, str]] = []

    for row_index, row in enumerate(rows):
        if not row["brinco"].upper().startswith("B"):
            continue
        candidates = [
            index
            for index in by_name.get(normalize(row["nome"]), [])
            if index not in used
        ]
        if len(candidates) == 1:
            matches[row_index] = candidates[0]
            used.add(candidates[0])

    for row_index, row in enumerate(rows):
        if row_index in matches:
            continue
        number = numeric_key(row["brinco"])
        candidates = [
            index
            for index in by_number.get(number, [])
            if index not in used
        ] if number is not None else []
        if not candidates:
            continue
        if len(candidates) > 1:
            exact = [
                index
                for index in candidates
                if normalize(animals[index]["nome"])
                == normalize(row["nome"])
            ]
            if len(exact) == 1:
                candidates = exact
            else:
                ambiguities.append(
                    (
                        row["brinco"],
                        row["nome"],
                        tuple(
                            f'{animals[index]["numero"]}/{animals[index]["nome"]}'
                            for index in candidates
                        ),
                    )
                )
                continue
        animal_index = candidates[0]
        matches[row_index] = animal_index
        used.add(animal_index)
        animal = animals[animal_index]
        if normalize(animal["nome"]) != normalize(row["nome"]):
            divergences.append(
                (
                    row["brinco"],
                    row["nome"],
                    str(animal["numero"]),
                    str(animal["nome"]),
                )
            )

    for row_index, row in enumerate(rows):
        if row_index in matches:
            continue
        candidates = [
            index
            for index in by_name.get(normalize(row["nome"]), [])
            if index not in used
        ]
        if len(candidates) == 1:
            matches[row_index] = candidates[0]
            used.add(candidates[0])

    return MatchResult(
        matched_pairs=tuple(sorted(matches.items())),
        ambiguities=tuple(ambiguities),
        divergences=tuple(divergences),
    )


def _new_animal_id(tag: str, name: str, occupied: set[str]) -> str:
    base = "v" + re.sub(r"[^A-Za-z0-9]", "", tag)
    if not base or base == "v":
        base = "v" + re.sub(r"[^A-Za-z0-9]", "", normalize(name).title())
    candidate = base or "vAnimal"
    suffix = 2
    while candidate in occupied:
        candidate = f"{base}-{suffix}"
        suffix += 1
    occupied.add(candidate)
    return candidate


def apply_report_rows(
    state: Mapping[str, Any], rows: Sequence[Mapping[str, str]]
) -> ImportResult:
    updated = copy.deepcopy(state)
    animals = updated.setdefault("vacas", [])
    base_count_before = len(animals)
    match = match_report_rows(updated, rows)
    matched = dict(match.matched_pairs)
    occupied_ids = {str(animal.get("id", "")) for animal in animals}
    changes: list[tuple[str, str, str, str, str]] = []
    lot_change_count = 0
    calving_change_count = 0
    new_animal_count = 0

    for row_index, row in enumerate(rows):
        lot = LOTE_MAP[row["lote"]]
        calving = iso_date(row["data"])
        days_in_milk: int | str = int(row["delx"]) if row["delx"] else ""
        name = (
            row["nome"]
            if normalize(row["nome"]) != normalize(row["brinco"])
            else row["brinco"]
        )
        if row_index in matched:
            animal = animals[matched[row_index]]
            if animal.get("lote") != lot:
                changes.append(
                    (
                        "lote",
                        str(animal["numero"]),
                        str(animal["nome"]),
                        str(animal.get("lote", "")),
                        lot,
                    )
                )
                lot_change_count += 1
            animal["lote"] = lot
            if calving and animal.get("parto") != calving:
                changes.append(
                    (
                        "parto",
                        str(animal["numero"]),
                        str(animal["nome"]),
                        str(animal.get("parto", "")),
                        calving,
                    )
                )
                calving_change_count += 1
            if calving:
                animal["parto"] = calving
            animal["del"] = days_in_milk
            animal["brinco"] = row["brinco"]
            continue

        new_animal_count += 1
        animals.append(
            {
                "id": _new_animal_id(row["brinco"], name, occupied_ids),
                "numero": row["brinco"],
                "brinco": row["brinco"],
                "nome": name,
                "lote": lot,
                "nascimento": "",
                "parto": calving,
                "peso": "",
                "media": 0,
                "del": days_in_milk,
                "situacao": "Em lactação" if days_in_milk != "" else "Seca",
                "ultimaMedicao": "",
                "status": "Ativo",
                "historico": [],
            }
        )

    for animal in animals:
        animal.setdefault("del", "")

    updated = repair_animal_ids(updated)
    legacy_only = tuple(
        (
            str(animal["numero"]),
            str(animal["nome"]),
            str(animal.get("lote", "")),
            str(animal.get("situacao", "")),
            len(animal.get("historico", [])),
        )
        for animal in updated["vacas"]
        if "brinco" not in animal
    )
    return ImportResult(
        state=updated,
        match=match,
        row_count=len(rows),
        base_count_before=base_count_before,
        new_animal_count=new_animal_count,
        lot_change_count=lot_change_count,
        calving_change_count=calving_change_count,
        changes=tuple(changes),
        legacy_only=legacy_only,
    )


def render_import_report(result: ImportResult) -> str:
    lines = [
        (
            f"Registros no PDF: {result.row_count} | "
            f"vacas na base antes: {result.base_count_before} | "
            f"depois: {len(result.state['vacas'])}"
        ),
        (
            f"Casadas com a base: {result.match.matched_count} | "
            f"novas cadastradas: {result.new_animal_count}"
        ),
        (
            f"Lote alterado: {result.lot_change_count} | "
            f"Data último parto alterada: {result.calving_change_count}"
        ),
        "",
        (
            "--- Vacas da base que NÃO aparecem no relatório "
            f"(mantidas, sem alteração): {len(result.legacy_only)}"
        ),
    ]
    for number, name, lot, situation, history_count in result.legacy_only:
        lines.append(
            f"    {number:<12} {name:<24} lote={lot:<18} "
            f"situacao={situation:<12} leituras={history_count}"
        )
    lines.extend(
        [
            "",
            (
                "--- Nome diverge entre relatório e base "
                f"(nome da base foi mantido): {len(result.match.divergences)}"
            ),
        ]
    )
    for tag, pdf_name, number, base_name in result.match.divergences:
        lines.append(
            f"    brinco {tag:<8} pdf={pdf_name:<20} "
            f"base={number}/{base_name}"
        )
    warnings = find_del_situation_warnings(result.state)
    lines.extend(["", f"--- Avisos DEL/situação: {len(warnings)}"])
    for warning in warnings:
        lines.append(
            f"    id={warning.animal_id:<24} "
            f"numero={warning.number:<12} brinco={warning.tag:<12} "
            f"nome={warning.name:<24} situacao={warning.situation} DEL=vazio"
        )
    lines.extend(["", f"--- Ambíguas (não atualizadas): {len(result.match.ambiguities)}"])
    for ambiguity in result.match.ambiguities:
        lines.append(f"    {ambiguity}")
    lines.extend(["", f"--- Alterações aplicadas: {len(result.changes)}"])
    for field, number, name, old, new in result.changes:
        lines.append(
            f"    {field:<6} {number:<12} {name:<24} {old:<14} -> {new}"
        )
    animals = result.state["vacas"]
    lines.extend(
        [
            "",
            (
                "Vacas com histórico de leite: "
                f"{sum(1 for animal in animals if animal.get('historico'))} | "
                "leituras totais: "
                f"{sum(len(animal.get('historico', [])) for animal in animals)}"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    platform = Path(__file__).resolve().parent
    parser.add_argument(
        "--canonical", type=Path, default=platform / "state_canonical.json"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=platform / "import_relatorio_animais_ultimo_relatorio.txt",
    )
    parser.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = read_pdf_rows(args.pdf)
    state = load_json_object(args.canonical)
    result = apply_report_rows(state, rows)
    report = render_import_report(result)
    atomic_write_text(args.report, report)
    if args.write:
        require_valid(result.state)
        atomic_write_text(args.canonical, encode_json(result.state))
        print("estado canônico gravado")
    else:
        print("simulação concluída; estado canônico não alterado")
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
