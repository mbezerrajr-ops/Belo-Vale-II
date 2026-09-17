from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping


STATE_PATTERN = re.compile(
    r'<script id="state-data" type="application/json">([\s\S]*?)</script>'
)


@dataclass(frozen=True)
class StateSummary:
    animal_count: int
    measurement_count: int
    measurements_by_date: dict[str, int]
    supply_count: int
    user_count: int


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    del_situation_warning_count: int


def extract_state_from_html(html: str) -> dict[str, Any]:
    match = STATE_PATTERN.search(html)
    if match is None:
        raise ValueError("state-data block not found")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("state-data must contain a JSON object")
    return value


def inject_state_into_html(template: str, state: Mapping[str, Any]) -> str:
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    replacement = (
        '<script id="state-data" type="application/json">'
        f"{encoded}</script>"
    )
    if "__STATE_JSON__" in template:
        return template.replace("__STATE_JSON__", encoded, 1)
    rendered, count = STATE_PATTERN.subn(replacement, template, count=1)
    if count != 1:
        raise ValueError("state-data block not found")
    return rendered


def summarize_state(state: Mapping[str, Any]) -> StateSummary:
    animals = list(state.get("vacas", []))
    dates = Counter(
        entry["data"]
        for animal in animals
        for entry in animal.get("historico", [])
    )
    return StateSummary(
        animal_count=len(animals),
        measurement_count=sum(dates.values()),
        measurements_by_date=dict(sorted(dates.items())),
        supply_count=len(state.get("insumos", [])),
        user_count=len(state.get("usuarios", [])),
    )


def _ascii_slug(value: str) -> str:
    ascii_value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def repair_animal_ids(state: Mapping[str, Any]) -> dict[str, Any]:
    repaired = copy.deepcopy(state)
    animals = repaired.get("vacas", [])
    raw_ids = [str(animal.get("id", "")).strip() for animal in animals]
    counts = Counter(raw_ids)
    target_indexes = [
        index
        for index, animal_id in enumerate(raw_ids)
        if not animal_id or counts[animal_id] > 1
    ]
    occupied = {
        animal_id
        for animal_id in raw_ids
        if animal_id and counts[animal_id] == 1
    }

    def identity(index: int) -> tuple[str, str, str, int]:
        animal = animals[index]
        return (
            str(animal.get("brinco", "")),
            str(animal.get("numero", "")),
            str(animal.get("nome", "")),
            index,
        )

    for index in sorted(target_indexes, key=identity):
        animal = animals[index]
        old_id = raw_ids[index]
        business_identifier = str(
            animal.get("brinco") or animal.get("numero") or ""
        )
        candidate = _ascii_slug(
            "-".join(
                part
                for part in (
                    old_id or "v",
                    business_identifier,
                    str(animal.get("nome", "")),
                )
                if part
            )
        ) or "v-animal"
        unique_candidate = candidate
        suffix = 2
        while unique_candidate in occupied:
            unique_candidate = f"{candidate}-{suffix}"
            suffix += 1
        animal["id"] = unique_candidate
        occupied.add(unique_candidate)

    return repaired


def project_state_without_history(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    projected = copy.deepcopy(state)
    for animal in projected.get("vacas", []):
        animal.pop("historico", None)
    return projected


def validate_state(
    state: Mapping[str, Any], expected: StateSummary | None = None
) -> ValidationReport:
    animals = list(state.get("vacas", []))
    ids = [str(animal.get("id", "")).strip() for animal in animals]
    duplicates = tuple(
        sorted(key for key, count in Counter(ids).items() if count > 1)
    )
    errors: list[str] = []
    if "" in ids:
        errors.append("animal_id_empty")
    if duplicates:
        errors.append("animal_ids_not_unique")
    summary = summarize_state(state)
    if expected is not None and summary != expected:
        errors.append("baseline_summary_changed")
    del_situation_warnings = [
        animal
        for animal in animals
        if "brinco" in animal
        and str(animal.get("del", "")) == ""
        and animal.get("situacao") == "Em lactação"
    ]
    warning_codes = (
        ("del_empty_while_lactating",) if del_situation_warnings else ()
    )
    return ValidationReport(
        errors=tuple(errors),
        warnings=warning_codes,
        duplicate_ids=duplicates,
        del_situation_warning_count=len(del_situation_warnings),
    )
