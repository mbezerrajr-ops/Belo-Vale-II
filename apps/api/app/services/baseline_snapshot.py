"""Leitura e validação do estado canônico legado.

Domínio puro, sem banco e sem efeito colateral: transforma o JSON canônico em
estruturas imutáveis e detecta qualquer divergência **antes** de qualquer
escrita. Nenhuma correção é aplicada aqui — divergência vira erro, não conserto
silencioso.

Usuários e credenciais legadas são deliberadamente ignorados: a migração não
transporta contas antigas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from app.services.brinco import normalize_brinco


class BaselineValidationError(ValueError):
    """Divergência estrutural que impede a migração."""


@dataclass(frozen=True)
class ExpectedCounts:
    animal_count: int
    measurement_count: int
    measurements_by_date: Mapping[date, int]
    supply_count: int = 4


#: Contagens confirmadas da baseline. Qualquer desvio precisa ser explicado
#: antes de migrar, nunca acomodado.
EXPECTED_BASELINE = ExpectedCounts(
    animal_count=401,
    measurement_count=152,
    measurements_by_date={date(2026, 7, 22): 107, date(2026, 8, 25): 45},
)


@dataclass(frozen=True)
class MeasurementRecord:
    measured_on: date
    producao: float
    lote_observado: str | None


@dataclass(frozen=True)
class AnimalRecord:
    legacy_id: str
    numero_legado: str | None
    name: str | None
    brinco: str | None
    brinco_origem: str | None
    situacao: str | None
    status: str | None
    lote: str | None
    ultimo_parto: date | None
    nascimento: date | None
    peso: float | None
    observacoes: str | None
    measurements: tuple[MeasurementRecord, ...] = field(default=())


@dataclass(frozen=True)
class SupplyDietRecord:
    lote: str
    kg_per_day: float


@dataclass(frozen=True)
class SupplyPriceRecord:
    effective_on: date
    price_per_kg: float


@dataclass(frozen=True)
class SupplyRecord:
    legacy_id: str
    name: str
    price_per_kg: float
    prices: tuple[SupplyPriceRecord, ...] = field(default=())
    diets: tuple[SupplyDietRecord, ...] = field(default=())


@dataclass(frozen=True)
class BaselineSnapshot:
    animals: tuple[AnimalRecord, ...]
    source_sha256: str
    supplies: tuple[SupplyRecord, ...] = field(default=())
    #: Preço pago por litro de leite. Base do cálculo de receita.
    milk_price_per_liter: float | None = None

    @property
    def animal_count(self) -> int:
        return len(self.animals)

    @property
    def measurement_count(self) -> int:
        return sum(len(animal.measurements) for animal in self.animals)

    def require_valid(self, *, expected: ExpectedCounts | None) -> None:
        errors = validate_snapshot(self, expected=expected)
        if errors:
            raise BaselineValidationError("; ".join(errors))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _parse_date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    return date.fromisoformat(text)


def _parse_float(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    return float(text)


def _parse_animal(raw: Mapping[str, Any]) -> AnimalRecord:
    brinco_origem = _text(raw.get("brinco"))
    brinco = normalize_brinco(brinco_origem)

    observacoes = None
    if brinco_origem and brinco is None:
        # O valor não identifica um animal, mas foi lido de uma ficha real:
        # registrar em vez de descartar silenciosamente.
        observacoes = (
            f"Brinco ilegível na baseline legada: {brinco_origem!r}. "
            "Animal preservado sem brinco; não recebe matching automático "
            "até que um brinco legível seja vinculado."
        )

    lote = _text(raw.get("lote"))
    measurements = tuple(
        MeasurementRecord(
            measured_on=_parse_date(entry.get("data")),
            producao=float(entry.get("producao")),
            lote_observado=lote,
        )
        for entry in (raw.get("historico") or [])
    )

    return AnimalRecord(
        legacy_id=str(raw.get("id") or "").strip(),
        numero_legado=_text(raw.get("numero")),
        name=_text(raw.get("nome")),
        brinco=brinco,
        brinco_origem=brinco_origem,
        situacao=_text(raw.get("situacao")),
        status=_text(raw.get("status")),
        lote=lote,
        ultimo_parto=_parse_date(raw.get("parto")),
        nascimento=_parse_date(raw.get("nascimento")),
        peso=_parse_float(raw.get("peso")),
        observacoes=observacoes,
        measurements=measurements,
    )


def _parse_supply(raw: Mapping[str, Any]) -> SupplyRecord:
    dieta = raw.get("dieta") or {}
    return SupplyRecord(
        legacy_id=str(raw.get("id") or "").strip(),
        name=_text(raw.get("nome")) or "",
        price_per_kg=float(raw.get("precoKg") or 0),
        prices=tuple(
            SupplyPriceRecord(
                effective_on=_parse_date(entry.get("data")),
                price_per_kg=float(entry.get("preco") or 0),
            )
            for entry in (raw.get("historico") or [])
        ),
        diets=tuple(
            SupplyDietRecord(lote=str(lote), kg_per_day=float(kg or 0))
            for lote, kg in sorted(dieta.items())
        ),
    )


def parse_baseline(text: str) -> BaselineSnapshot:
    """Lê o estado canônico. Não lê usuários nem credenciais."""
    state = json.loads(text)
    animals = tuple(_parse_animal(raw) for raw in state.get("vacas", []))
    supplies = tuple(_parse_supply(raw) for raw in state.get("insumos", []))
    milk_price = state.get("precoLeite")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return BaselineSnapshot(
        animals=animals,
        source_sha256=digest,
        supplies=supplies,
        milk_price_per_liter=float(milk_price) if milk_price is not None else None,
    )


def validate_snapshot(
    snapshot: BaselineSnapshot, *, expected: ExpectedCounts | None
) -> list[str]:
    """Devolve *todos* os problemas encontrados, não apenas o primeiro."""
    errors: list[str] = []

    seen_legacy: dict[str, int] = {}
    seen_brinco: dict[str, int] = {}
    for animal in snapshot.animals:
        if not animal.legacy_id:
            errors.append("legacy_id vazio encontrado; identidade de migração é obrigatória")
            continue
        seen_legacy[animal.legacy_id] = seen_legacy.get(animal.legacy_id, 0) + 1
        if animal.brinco:
            seen_brinco[animal.brinco] = seen_brinco.get(animal.brinco, 0) + 1

        dates: set[date] = set()
        for measurement in animal.measurements:
            if measurement.measured_on is None:
                errors.append(f"{animal.legacy_id}: medição sem data")
                continue
            if measurement.measured_on in dates:
                errors.append(
                    f"{animal.legacy_id}: medição duplicada em "
                    f"{measurement.measured_on.isoformat()}"
                )
            dates.add(measurement.measured_on)

    errors.extend(
        f"legacy_id duplicado: {value!r} ({count} ocorrências)"
        for value, count in sorted(seen_legacy.items())
        if count > 1
    )
    errors.extend(
        f"brinco duplicado: {value!r} ({count} ocorrências)"
        for value, count in sorted(seen_brinco.items())
        if count > 1
    )

    if expected is not None:
        if len(snapshot.supplies) != expected.supply_count:
            errors.append(
                f"esperados {expected.supply_count} insumos, "
                f"encontrados {len(snapshot.supplies)}"
            )
        if snapshot.animal_count != expected.animal_count:
            errors.append(
                f"esperados {expected.animal_count} animais, "
                f"encontrados {snapshot.animal_count}"
            )
        if snapshot.measurement_count != expected.measurement_count:
            errors.append(
                f"esperadas {expected.measurement_count} medições, "
                f"encontradas {snapshot.measurement_count}"
            )
        actual_by_date: dict[date, int] = {}
        for animal in snapshot.animals:
            for measurement in animal.measurements:
                if measurement.measured_on is not None:
                    actual_by_date[measurement.measured_on] = (
                        actual_by_date.get(measurement.measured_on, 0) + 1
                    )
        if actual_by_date != dict(expected.measurements_by_date):
            errors.append(
                f"distribuição por data divergente: esperada "
                f"{dict(expected.measurements_by_date)}, encontrada {actual_by_date}"
            )

    return errors


def animals_by_legacy_id(
    animals: Sequence[AnimalRecord],
) -> dict[str, AnimalRecord]:
    return {animal.legacy_id: animal for animal in animals}
