from __future__ import annotations

import copy
import json
import re
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
