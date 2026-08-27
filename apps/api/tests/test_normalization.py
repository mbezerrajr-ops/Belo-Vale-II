from datetime import date
from decimal import Decimal

from app.services.normalization import normalize_date, normalize_decimal, normalize_line


def test_normalize_decimal_accepts_comma_as_the_separator() -> None:
    assert normalize_decimal("18,5") == Decimal("18.5")


def test_normalize_decimal_accepts_dot_as_the_separator() -> None:
    assert normalize_decimal("18.5") == Decimal("18.5")


def test_normalize_decimal_returns_none_for_blank_or_unparseable_input() -> None:
    assert normalize_decimal(None) is None
    assert normalize_decimal("  ") is None
    assert normalize_decimal("abc") is None


def test_normalize_date_resolves_a_two_digit_year_against_the_century_base() -> None:
    assert normalize_date("22/07/26") == date(2026, 7, 22)
    assert normalize_date("22/07/26", century_base=1900) == date(1926, 7, 22)


def test_normalize_date_accepts_a_four_digit_year_and_dash_separators() -> None:
    assert normalize_date("22-07-2026") == date(2026, 7, 22)


def test_normalize_date_returns_none_for_an_invalid_calendar_date() -> None:
    assert normalize_date("31/02/26") is None
    assert normalize_date("not a date") is None
    assert normalize_date(None) is None


def test_normalize_line_combines_all_raw_fields() -> None:
    line = normalize_line(
        raw_animal_number=" 497 ",
        raw_animal_name=" Ponta Curta ",
        raw_morning="10",
        raw_afternoon="8",
        raw_total="18,5",
        raw_date="22/07/26",
        raw_lot=" 1 ",
        raw_notes="  ",
    )

    assert line.animal_number == "497"
    assert line.animal_name == "Ponta Curta"
    assert line.morning == Decimal("10")
    assert line.afternoon == Decimal("8")
    assert line.total == Decimal("18.5")
    assert line.measured_on == date(2026, 7, 22)
    assert line.lot == "1"
    assert line.notes is None
