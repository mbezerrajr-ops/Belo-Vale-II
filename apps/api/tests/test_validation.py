from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.services.animal_matching import (
    MATCH_BY_BRINCO,
    MATCH_NONE,
    AnimalMatchResult,
)
from app.services.normalization import NormalizedLine
from app.services.validation import (
    ALERT_AMBIGUOUS_ANIMAL,
    ALERT_DATE_MISMATCH,
    ALERT_DUPLICATE_MEASUREMENT,
    ALERT_IMPLAUSIBLE_VALUE,
    ALERT_LOT_MISMATCH,
    ALERT_MISSING_HEADER,
    ALERT_MISSING_REQUIRED_VALUE,
    ALERT_SIDE_OBSERVATION,
    ALERT_TOTAL_MISMATCH,
    ALERT_UNKNOWN_ANIMAL,
    ValidationContext,
    validate_line,
)


class _Animal:
    def __init__(self) -> None:
        self.id = uuid4()


def _line(**overrides: object) -> NormalizedLine:
    defaults: dict[str, object] = dict(
        animal_brinco="497",
        animal_number="497",
        animal_name="PONTA CURTA",
        morning=Decimal("10"),
        afternoon=Decimal("8"),
        total=Decimal("18"),
        measured_on=date(2026, 7, 22),
        lot="1",
        notes=None,
    )
    defaults.update(overrides)
    return NormalizedLine(**defaults)  # type: ignore[arg-type]


def _matched_context(**overrides: object) -> ValidationContext:
    animal = _Animal()
    defaults: dict[str, object] = dict(
        match=AnimalMatchResult(
            animal=animal,
            is_ambiguous=False,
            candidate_count=1,
            method=MATCH_BY_BRINCO,
            brinco_lido="497",
            brinco_normalizado="497",
            reason=None,
        ),  # type: ignore[arg-type]
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)  # type: ignore[arg-type]


def test_clean_line_has_no_alerts_and_high_confidence() -> None:
    result = validate_line(_line(), _matched_context())

    assert result.alerts == []
    # No history was supplied, so the "implausible value" factor is an
    # unverifiable 0.5 rather than a false 1.0 — confidence reflects that.
    assert 0.9 < result.final_confidence < 1.0
    assert result.candidate_animal_id is not None


def test_clean_line_reaches_full_confidence_with_supporting_history() -> None:
    result = validate_line(
        _line(),
        _matched_context(history_totals=[Decimal("17"), Decimal("18"), Decimal("19")]),
    )

    assert result.alerts == []
    assert result.final_confidence == 1.0


def test_total_mismatch_is_an_explained_alert() -> None:
    result = validate_line(_line(morning=Decimal("10"), afternoon=Decimal("8"), total=Decimal("25")), _matched_context())

    assert result.has_code(ALERT_TOTAL_MISMATCH)
    alert = next(a for a in result.alerts if a.code == ALERT_TOTAL_MISMATCH)
    assert alert.details["expected_total"] == "18"
    assert alert.details["reported_total"] == "25"


def test_unknown_animal_is_flagged_and_has_no_candidate_id() -> None:
    context = ValidationContext(
        match=AnimalMatchResult(
            animal=None,
            is_ambiguous=False,
            candidate_count=0,
            method=MATCH_NONE,
            brinco_lido="497",
            brinco_normalizado="497",
            reason="Nenhum animal cadastrado tem este brinco.",
        )
    )

    result = validate_line(_line(), context)

    assert result.has_code(ALERT_UNKNOWN_ANIMAL)
    assert result.candidate_animal_id is None


def test_ambiguous_animal_is_flagged_with_candidate_count() -> None:
    context = ValidationContext(
        match=AnimalMatchResult(
            animal=None,
            is_ambiguous=True,
            candidate_count=3,
            method=MATCH_NONE,
            brinco_lido="497",
            brinco_normalizado="497",
            reason="Mais de um animal cadastrado tem este brinco.",
        )
    )

    result = validate_line(_line(), context)

    assert result.has_code(ALERT_AMBIGUOUS_ANIMAL)
    alert = next(a for a in result.alerts if a.code == ALERT_AMBIGUOUS_ANIMAL)
    assert alert.details["candidate_count"] == 3


def test_missing_brinco_is_flagged() -> None:
    result = validate_line(_line(animal_brinco=None), _matched_context())

    assert result.has_code(ALERT_MISSING_HEADER)


def test_name_and_number_do_not_replace_a_missing_brinco() -> None:
    """Sem brinco não há correspondência automática, por mais que a linha
    traga número e nome legíveis."""
    result = validate_line(
        _line(animal_brinco=None, animal_number="497", animal_name="PONTA CURTA"),
        _matched_context(),
    )

    assert result.has_code(ALERT_MISSING_HEADER)


def test_readable_brinco_does_not_raise_the_header_alert() -> None:
    result = validate_line(
        _line(animal_brinco="497", animal_number=None, animal_name=None),
        _matched_context(),
    )

    assert not result.has_code(ALERT_MISSING_HEADER)


def test_missing_total_is_flagged_as_a_required_value() -> None:
    result = validate_line(_line(total=None), _matched_context())

    assert result.has_code(ALERT_MISSING_REQUIRED_VALUE)


def test_lot_mismatch_is_flagged_when_declared_and_header_lots_diverge() -> None:
    result = validate_line(
        _line(),
        _matched_context(declared_lot="2", header_lot="1"),
    )

    assert result.has_code(ALERT_LOT_MISMATCH)


def test_date_mismatch_is_flagged_when_declared_and_header_dates_diverge() -> None:
    result = validate_line(
        _line(),
        _matched_context(
            declared_measured_on=date(2026, 7, 23), header_measured_on=date(2026, 7, 22)
        ),
    )

    assert result.has_code(ALERT_DATE_MISMATCH)


def test_duplicate_measurement_is_flagged_for_an_existing_active_date() -> None:
    result = validate_line(
        _line(measured_on=date(2026, 7, 22)),
        _matched_context(existing_measurement_dates=frozenset({date(2026, 7, 22)})),
    )

    assert result.has_code(ALERT_DUPLICATE_MEASUREMENT)


def test_implausible_value_is_flagged_against_history() -> None:
    result = validate_line(
        _line(total=Decimal("40")),
        _matched_context(history_totals=[Decimal("18"), Decimal("19"), Decimal("20")]),
    )

    assert result.has_code(ALERT_IMPLAUSIBLE_VALUE)


def test_side_observation_is_informational_and_does_not_reduce_confidence() -> None:
    with_notes = validate_line(_line(notes="vaca mancando"), _matched_context())
    without_notes = validate_line(_line(notes=None), _matched_context())

    assert with_notes.has_code(ALERT_SIDE_OBSERVATION)
    alert = next(a for a in with_notes.alerts if a.code == ALERT_SIDE_OBSERVATION)
    assert alert.severity == "info"
    # Presence of a side note contributes no confidence factor of its own, so
    # it must not change the score relative to an otherwise identical line.
    assert with_notes.final_confidence == without_notes.final_confidence


def test_confidence_never_hides_a_hard_alert() -> None:
    """A single missing required field must not be masked by otherwise-good factors."""
    result = validate_line(_line(total=None), _matched_context())

    assert result.final_confidence < 1.0
    assert result.has_code(ALERT_MISSING_REQUIRED_VALUE)
