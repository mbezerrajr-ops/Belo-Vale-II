from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

_DATE_SEPARATORS = re.compile(r"[/-]")


@dataclass(frozen=True)
class NormalizedLine:
    #: Brinco lido, como veio da ficha. A normalização canônica acontece no
    #: matching, que preserva o valor bruto para auditoria.
    animal_brinco: str | None
    #: Número e nome continuam sendo lidos e exibidos ao revisor como
    #: evidência, mas nunca são usados para correspondência automática.
    animal_number: str | None
    animal_name: str | None
    morning: Decimal | None
    afternoon: Decimal | None
    total: Decimal | None
    measured_on: date | None
    lot: str | None
    notes: str | None


def _clean_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def normalize_decimal(raw: str | None) -> Decimal | None:
    """Accepts a comma or dot as the decimal separator; anything else is unparseable."""
    cleaned = _clean_text(raw)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned.replace(",", "."))
    except InvalidOperation:
        return None


def normalize_date(raw: str | None, *, century_base: int = 2000) -> date | None:
    """Parses dd/mm/yy or dd/mm/yyyy (also accepting '-' as separator).

    A two-digit year is resolved against `century_base` — the plan's "configured
    century window" — rather than assumed, since this farm's photographed sheets
    only ever fall within one century in practice.
    """
    cleaned = _clean_text(raw)
    if cleaned is None:
        return None
    parts = _DATE_SEPARATORS.split(cleaned)
    if len(parts) != 3:
        return None
    day_text, month_text, year_text = parts
    try:
        day, month, year = int(day_text), int(month_text), int(year_text)
    except ValueError:
        return None
    if len(year_text) == 2:
        year += century_base
    try:
        return date(year, month, day)
    except ValueError:
        return None


def normalize_line(
    *,
    raw_animal_brinco: str | None = None,
    raw_animal_number: str | None = None,
    raw_animal_name: str | None = None,
    raw_morning: str | None = None,
    raw_afternoon: str | None = None,
    raw_total: str | None = None,
    raw_date: str | None = None,
    raw_lot: str | None = None,
    raw_notes: str | None = None,
    century_base: int = 2000,
) -> NormalizedLine:
    return NormalizedLine(
        animal_brinco=_clean_text(raw_animal_brinco),
        animal_number=_clean_text(raw_animal_number),
        animal_name=_clean_text(raw_animal_name),
        morning=normalize_decimal(raw_morning),
        afternoon=normalize_decimal(raw_afternoon),
        total=normalize_decimal(raw_total),
        measured_on=normalize_date(raw_date, century_base=century_base),
        lot=_clean_text(raw_lot),
        notes=_clean_text(raw_notes),
    )
