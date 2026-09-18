"""Indicadores do painel do rebanho.

Porta o que a plataforma legada calculava, agora sobre os dados no banco. As
fórmulas são deliberadamente as mesmas, para que os números não mudem de
significado na troca de sistema:

- **custo do lote** = Σ (dieta em kg/dia × preço por kg) de cada insumo;
- **custo por vaca** = custo do lote ÷ vacas daquele lote, porque a dieta é
  controlada por lote e não por animal;
- **receita** = produção × preço do leite;
- **DEL** = dias entre o último parto e a data de referência, derivado na
  leitura e nunca persistido.

Quando falta o preço do leite, receita e lucro saem como ``None`` em vez de
zero: não saber quanto se recebe por litro é diferente de não receber nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.lot_kind import KIND_DIET, KIND_MANAGEMENT
from app.db.models import (
    Animal,
    AnimalLotAssignment,
    Farm,
    OfficialMeasurement,
    Supply,
    SupplyDiet,
)

#: Faixas de dias em lactação. Espelham as do painel legado.
_STAGES: tuple[tuple[str, int, int | None], ...] = (
    ("0-100", 0, 100),
    ("101-200", 101, 200),
    ("201-305", 201, 305),
    ("305+", 306, None),
)

SEM_LOTE = "sem lote"


def lactation_stage(last_calving: date | None, reference: date) -> str | None:
    """Faixa de dias em lactação, ou ``None`` quando não há parto registrado.

    Sem data de parto não existe DEL. Inventar um valor — zero, por exemplo —
    contaminaria os indicadores reprodutivos, que é exatamente o que os 30
    alertas da baseline apontam.
    """
    if last_calving is None:
        return None
    days = (reference - last_calving).days
    if days < 0:
        return None
    for label, start, end in _STAGES:
        if days >= start and (end is None or days <= end):
            return label
    return None


@dataclass
class LotSummary:
    lote: str
    animals: int
    production: float
    feed_cost: float
    revenue: float | None
    profit: float | None
    cost_per_animal: float
    production_per_animal: float
    cost_ratio: float


@dataclass
class SupplyBreakdown:
    name: str
    price_per_kg: float
    total_cost: float
    cost_by_lot: dict[str, float]


@dataclass
class ProducerEntry:
    animal_id: UUID
    brinco: str | None
    name: str | None
    lote: str | None
    production: float


@dataclass
class ProductionPoint:
    measured_on: date
    liters: float
    animals: int


@dataclass
class DashboardSummary:
    measured_on: date | None
    available_dates: list[date]
    #: Série para o gráfico de tendência: total lido em cada data de coleta.
    production_by_date: list[ProductionPoint]
    milk_price: float | None
    total_animals: int
    animals_without_lot: int
    animals_with_reading: int
    by_situation: dict[str, int]
    by_status: dict[str, int]
    #: Quantos animais em cada área/categoria da fazenda (BEZERREIRO, ENGORDA…).
    #: Não são lotes: não têm dieta nem custo.
    by_management_group: dict[str, int]
    lactation_stages: dict[str, int]
    lots: list[LotSummary] = field(default_factory=list)
    feed_breakdown: list[SupplyBreakdown] = field(default_factory=list)
    top_producers: list[ProducerEntry] = field(default_factory=list)
    bottom_producers: list[ProducerEntry] = field(default_factory=list)
    total_production: float = 0.0
    total_feed_cost: float = 0.0
    total_revenue: float | None = None
    total_profit: float | None = None


def _as_float(value: Decimal | float | None) -> float:
    return float(value) if value is not None else 0.0


def _producao(values: dict) -> float:
    """Produção de uma medição.

    A baseline grava `producao`; o pipeline de OCR grava `total`. Ler os dois
    evita que o painel ignore justamente as medições novas.
    """
    for key in ("producao", "total"):
        if values.get(key) is not None:
            try:
                return float(values[key])
            except (TypeError, ValueError):
                continue
    return 0.0


async def _current_lots(
    session: AsyncSession, farm_id: UUID, kind: str
) -> dict[UUID, str]:
    """Lotação vigente de um tipo, por animal."""
    rows = await session.execute(
        select(AnimalLotAssignment.animal_id, AnimalLotAssignment.lote)
        .join(Animal, Animal.id == AnimalLotAssignment.animal_id)
        .where(
            Animal.farm_id == farm_id,
            AnimalLotAssignment.kind == kind,
            AnimalLotAssignment.valid_to.is_(None),
        )
    )
    return {animal_id: lote for animal_id, lote in rows}


async def _feed_cost_by_lot(
    session: AsyncSession, farm_id: UUID
) -> tuple[dict[str, float], list[SupplyBreakdown]]:
    rows = await session.execute(
        select(Supply.name, Supply.price_per_kg, SupplyDiet.lote, SupplyDiet.kg_per_day)
        .join(SupplyDiet, SupplyDiet.supply_id == Supply.id)
        .where(Supply.farm_id == farm_id)
        .order_by(Supply.name, SupplyDiet.lote)
    )

    by_lot: dict[str, float] = {}
    per_supply: dict[str, SupplyBreakdown] = {}
    for name, price, lote, kg in rows:
        cost = _as_float(price) * _as_float(kg)
        by_lot[lote] = by_lot.get(lote, 0.0) + cost
        entry = per_supply.setdefault(
            name,
            SupplyBreakdown(
                name=name, price_per_kg=_as_float(price), total_cost=0.0, cost_by_lot={}
            ),
        )
        entry.cost_by_lot[lote] = entry.cost_by_lot.get(lote, 0.0) + cost
        entry.total_cost += cost

    return by_lot, sorted(per_supply.values(), key=lambda item: -item.total_cost)


async def build_dashboard(
    session: AsyncSession,
    *,
    farm_id: UUID,
    measured_on: date | None = None,
    lote: str | None = None,
    situacao: str | None = None,
) -> DashboardSummary:
    """Monta o painel.

    ``measured_on`` ausente usa a data de medição mais recente da fazenda, que
    é o que o operador espera ver ao abrir a tela.
    """
    farm = await session.scalar(select(Farm).where(Farm.id == farm_id))
    milk_price = _as_float(farm.milk_price_per_liter) if farm else 0.0
    has_milk_price = farm is not None and farm.milk_price_per_liter is not None

    available = list(
        await session.scalars(
            select(OfficialMeasurement.measured_on)
            .join(Animal, Animal.id == OfficialMeasurement.animal_id)
            .where(Animal.farm_id == farm_id, OfficialMeasurement.status == "active")
            .distinct()
            .order_by(OfficialMeasurement.measured_on.desc())
        )
    )
    reference = measured_on or (available[0] if available else None)

    # Tendência: total e cobertura de cada data, sem filtro — é a linha do
    # tempo da fazenda inteira, e um filtro de lote a esvaziaria.
    series_rows = await session.execute(
        select(OfficialMeasurement.measured_on, OfficialMeasurement.values)
        .join(Animal, Animal.id == OfficialMeasurement.animal_id)
        .where(Animal.farm_id == farm_id, OfficialMeasurement.status == "active")
    )
    by_date: dict[date, ProductionPoint] = {}
    for day, values in series_rows:
        point = by_date.setdefault(day, ProductionPoint(measured_on=day, liters=0.0, animals=0))
        point.liters += _producao(values or {})
        point.animals += 1
    production_by_date = [by_date[day] for day in sorted(by_date)]

    animals = list(
        await session.scalars(select(Animal).where(Animal.farm_id == farm_id))
    )
    # Lote de ordenha e grupo de manejo são coisas diferentes: só o primeiro
    # tem dieta e custo. Misturá-los faria a fazenda "ter" lotes sem dieta.
    lots = await _current_lots(session, farm_id, KIND_DIET)
    groups = await _current_lots(session, farm_id, KIND_MANAGEMENT)

    readings: dict[UUID, float] = {}
    if reference is not None:
        rows = await session.execute(
            select(OfficialMeasurement.animal_id, OfficialMeasurement.values)
            .join(Animal, Animal.id == OfficialMeasurement.animal_id)
            .where(
                Animal.farm_id == farm_id,
                OfficialMeasurement.status == "active",
                OfficialMeasurement.measured_on == reference,
            )
        )
        readings = {animal_id: _producao(values or {}) for animal_id, values in rows}

    selected = [
        animal
        for animal in animals
        if (lote is None or lots.get(animal.id) == lote)
        and (situacao is None or animal.situacao == situacao)
    ]

    by_situation: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_group: dict[str, int] = {}
    stages: dict[str, int] = {label: 0 for label, _, _ in _STAGES}
    without_lot = 0
    for animal in selected:
        by_situation[animal.situacao or "—"] = (
            by_situation.get(animal.situacao or "—", 0) + 1
        )
        by_status[animal.status or "—"] = by_status.get(animal.status or "—", 0) + 1
        if animal.id not in lots:
            without_lot += 1
        group = groups.get(animal.id)
        if group is not None:
            by_group[group] = by_group.get(group, 0) + 1
        if reference is not None:
            stage = lactation_stage(animal.ultimo_parto, reference)
            if stage is not None:
                stages[stage] += 1

    feed_by_lot, breakdown = await _feed_cost_by_lot(session, farm_id)

    # Lotes considerados: os que têm dieta e os que têm animais selecionados.
    lot_names = sorted(
        {lots[a.id] for a in selected if a.id in lots} | set(feed_by_lot)
        if lote is None
        else {lote}
    )

    lot_summaries: list[LotSummary] = []
    for name in lot_names:
        in_lot = [a for a in selected if lots.get(a.id) == name]
        production = sum(readings.get(a.id, 0.0) for a in in_lot)
        cost = feed_by_lot.get(name, 0.0)
        revenue = production * milk_price if has_milk_price else None
        lot_summaries.append(
            LotSummary(
                lote=name,
                animals=len(in_lot),
                production=production,
                feed_cost=cost,
                revenue=revenue,
                profit=(revenue - cost) if revenue is not None else None,
                cost_per_animal=cost / len(in_lot) if in_lot else 0.0,
                production_per_animal=production / len(in_lot) if in_lot else 0.0,
                cost_ratio=(cost / revenue) if revenue else 0.0,
            )
        )

    ranked = sorted(
        (
            ProducerEntry(
                animal_id=animal.id,
                brinco=animal.brinco,
                name=animal.name,
                lote=lots.get(animal.id),
                production=readings[animal.id],
            )
            for animal in selected
            if animal.id in readings
        ),
        key=lambda entry: entry.production,
        reverse=True,
    )

    total_production = sum(readings.get(a.id, 0.0) for a in selected)
    total_cost = sum(summary.feed_cost for summary in lot_summaries)
    total_revenue = total_production * milk_price if has_milk_price else None

    return DashboardSummary(
        measured_on=reference,
        available_dates=available,
        production_by_date=production_by_date,
        milk_price=milk_price if has_milk_price else None,
        total_animals=len(selected),
        animals_without_lot=without_lot,
        animals_with_reading=sum(1 for a in selected if a.id in readings),
        by_situation=by_situation,
        by_status=by_status,
        by_management_group=dict(sorted(by_group.items())),
        lactation_stages=stages,
        lots=lot_summaries,
        feed_breakdown=breakdown,
        top_producers=ranked[:10],
        bottom_producers=list(reversed(ranked[-10:])) if ranked else [],
        total_production=total_production,
        total_feed_cost=total_cost,
        total_revenue=total_revenue,
        total_profit=(total_revenue - total_cost) if total_revenue is not None else None,
    )
