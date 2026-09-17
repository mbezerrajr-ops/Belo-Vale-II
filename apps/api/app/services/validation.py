from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.services.animal_matching import AnimalMatchResult
from app.services.normalization import NormalizedLine

ALERT_UNKNOWN_ANIMAL = "unknown_animal"
ALERT_AMBIGUOUS_ANIMAL = "ambiguous_animal"
ALERT_LOT_MISMATCH = "lot_mismatch"
ALERT_DATE_MISMATCH = "date_mismatch"
ALERT_MISSING_HEADER = "missing_header"
ALERT_TOTAL_MISMATCH = "total_mismatch"
ALERT_DUPLICATE_MEASUREMENT = "duplicate_measurement"
ALERT_IMPLAUSIBLE_VALUE = "implausible_value"
ALERT_MISSING_REQUIRED_VALUE = "missing_required_value"
ALERT_SIDE_OBSERVATION = "side_observation"

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class Alert:
    code: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationContext:
    match: AnimalMatchResult
    history_totals: list[Decimal] = field(default_factory=list)
    existing_measurement_dates: frozenset[date] = frozenset()
    header_lot: str | None = None
    header_measured_on: date | None = None
    declared_lot: str | None = None
    declared_measured_on: date | None = None
    total_tolerance: Decimal = Decimal("0.5")
    implausible_ratio: Decimal = Decimal("2")


@dataclass(frozen=True)
class ValidationResult:
    final_confidence: float
    alerts: list[Alert]
    candidate_animal_id: UUID | None

    def has_code(self, code: str) -> bool:
        return any(alert.code == code for alert in self.alerts)


def validate_line(line: NormalizedLine, context: ValidationContext) -> ValidationResult:
    """Every alert here is independently explainable; nothing is inferred from an
    aggregate score. `final_confidence` only prioritizes the review queue — it
    never authorizes skipping review (that is enforced by Task 6, not here)."""
    alerts: list[Alert] = []
    factors: dict[str, float] = {}

    if context.match.is_ambiguous:
        alerts.append(
            Alert(
                ALERT_AMBIGUOUS_ANIMAL,
                "error",
                "Mais de um animal cadastrado tem este brinco.",
                {
                    "candidate_count": context.match.candidate_count,
                    "brinco_lido": context.match.brinco_lido,
                    "brinco_normalizado": context.match.brinco_normalizado,
                },
            )
        )
        factors["animal_match"] = 0.0
    elif context.match.animal is None:
        alerts.append(
            Alert(
                ALERT_UNKNOWN_ANIMAL,
                "error",
                context.match.reason
                or "Nenhum animal cadastrado corresponde ao brinco informado.",
                {
                    "brinco_lido": context.match.brinco_lido,
                    "brinco_normalizado": context.match.brinco_normalizado,
                    "match_method": context.match.method,
                },
            )
        )
        factors["animal_match"] = 0.0
    else:
        factors["animal_match"] = 1.0

    if line.animal_brinco is None:
        alerts.append(
            Alert(
                ALERT_MISSING_HEADER,
                "error",
                "Brinco ilegível ou ausente na linha: sem ele não há "
                "correspondência automática possível.",
            )
        )
        factors["header"] = 0.0
    else:
        factors["header"] = 1.0

    if line.total is None:
        alerts.append(
            Alert(
                ALERT_MISSING_REQUIRED_VALUE,
                "error",
                "Valor total da medição está ausente.",
                {"field": "total"},
            )
        )
        factors["required_values"] = 0.0
    else:
        factors["required_values"] = 1.0

    if line.morning is not None and line.afternoon is not None and line.total is not None:
        expected_total = line.morning + line.afternoon
        if abs(expected_total - line.total) > context.total_tolerance:
            alerts.append(
                Alert(
                    ALERT_TOTAL_MISMATCH,
                    "warning",
                    "Soma de manhã e tarde não confere com o total informado.",
                    {
                        "expected_total": str(expected_total),
                        "reported_total": str(line.total),
                    },
                )
            )
            factors["arithmetic"] = 0.0
        else:
            factors["arithmetic"] = 1.0
    else:
        factors["arithmetic"] = 0.5

    if (
        context.declared_lot is not None
        and context.header_lot is not None
        and context.declared_lot != context.header_lot
    ):
        alerts.append(
            Alert(
                ALERT_LOT_MISMATCH,
                "warning",
                "Lote declarado no envio diverge do lote lido na ficha.",
                {"declared_lot": context.declared_lot, "header_lot": context.header_lot},
            )
        )
        factors["lot_date"] = 0.0
    elif (
        context.declared_measured_on is not None
        and context.header_measured_on is not None
        and context.declared_measured_on != context.header_measured_on
    ):
        alerts.append(
            Alert(
                ALERT_DATE_MISMATCH,
                "warning",
                "Data declarada no envio diverge da data lida na ficha.",
                {
                    "declared_date": context.declared_measured_on.isoformat(),
                    "header_date": context.header_measured_on.isoformat(),
                },
            )
        )
        factors["lot_date"] = 0.0
    else:
        factors["lot_date"] = 1.0

    if line.measured_on is not None and line.measured_on in context.existing_measurement_dates:
        alerts.append(
            Alert(
                ALERT_DUPLICATE_MEASUREMENT,
                "warning",
                "Já existe uma medição oficial ativa para este animal nesta data.",
                {"measured_on": line.measured_on.isoformat()},
            )
        )
        factors["duplicate"] = 0.0
    else:
        factors["duplicate"] = 1.0

    if line.total is not None and context.history_totals:
        average = sum(context.history_totals) / len(context.history_totals)
        if average > 0 and (
            line.total > average * context.implausible_ratio
            or line.total < average / context.implausible_ratio
        ):
            alerts.append(
                Alert(
                    ALERT_IMPLAUSIBLE_VALUE,
                    "warning",
                    "Valor muito distante da média histórica do animal.",
                    {
                        "reported_total": str(line.total),
                        "historical_average": str(average),
                    },
                )
            )
            factors["history"] = 0.0
        else:
            factors["history"] = 1.0
    else:
        factors["history"] = 0.5

    if line.notes:
        alerts.append(
            Alert(
                ALERT_SIDE_OBSERVATION,
                "info",
                "Observação lateral registrada na ficha.",
                {"notes": line.notes},
            )
        )

    final_confidence = sum(factors.values()) / len(factors)

    return ValidationResult(
        final_confidence=final_confidence,
        alerts=alerts,
        candidate_animal_id=context.match.animal.id if context.match.animal else None,
    )
