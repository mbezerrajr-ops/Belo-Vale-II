"""Contratos HTTP do painel e dos insumos."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LotSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lote: str
    animals: int
    production: float
    feed_cost: float
    #: Nulo quando a fazenda não tem preço do leite definido — não saber
    #: quanto se recebe é diferente de não receber nada.
    revenue: float | None
    profit: float | None
    cost_per_animal: float
    production_per_animal: float
    cost_ratio: float


class SupplyBreakdownRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    price_per_kg: float
    total_cost: float
    cost_by_lot: dict[str, float]


class ProducerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    animal_id: UUID
    brinco: str | None
    name: str | None
    lote: str | None
    production: float


class ProductionPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    measured_on: date
    liters: float
    animals: int


class DashboardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    measured_on: date | None
    available_dates: list[date]
    production_by_date: list[ProductionPointRead]
    milk_price: float | None
    total_animals: int
    animals_without_lot: int
    animals_with_reading: int
    by_situation: dict[str, int]
    by_status: dict[str, int]
    by_management_group: dict[str, int]
    lactation_stages: dict[str, int]
    lots: list[LotSummaryRead]
    feed_breakdown: list[SupplyBreakdownRead]
    top_producers: list[ProducerRead]
    bottom_producers: list[ProducerRead]
    total_production: float
    total_feed_cost: float
    total_revenue: float | None
    total_profit: float | None


class DietRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lote: str
    kg_per_day: float


class SupplyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price_per_kg: float
    legacy_id: str | None
    diets: list[DietRead]


class SupplyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    price_per_kg: float = Field(ge=0)


class SupplyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    price_per_kg: float | None = Field(default=None, ge=0)
    #: Data de vigência do novo preço. O preço anterior fica no histórico.
    effective_on: date | None = None


class DietUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lote: str = Field(min_length=1, max_length=64)
    kg_per_day: float = Field(ge=0)


class MilkPriceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milk_price_per_liter: float = Field(ge=0)
