from datetime import date
from pydantic import BaseModel, Field


class MonthResult(BaseModel):
    month: str
    start: date
    end: date
    elapsed_days: int
    calendar_days: int
    in_progress: bool
    reading_days: int
    reading_count: int
    animals_read: int
    animals_per_collection_min: int | None
    animals_per_collection_max: int | None
    recorded_liters: float
    average_liters_per_collection: float | None
    average_liters_per_animal_reading: float | None
    estimated_liters: float | None
    estimated_revenue: float | None
    estimated_feed_cost: float | None
    estimated_result: float | None
    margin_pct: float | None
    production_change_pct: float | None = None
    result_change: float | None = None
    status: str
    milk_price_days: int
    diet_days: int
    assumed_days: int
    warnings: list[str] = Field(default_factory=list)


class MonthlyReport(BaseModel):
    generated_on: date
    farm_name: str
    start_month: str
    end_month: str
    current_values_simulation: bool
    method: str
    months: list[MonthResult]
    best_month: str | None = None
    worst_month: str | None = None
    positive_months: int
    negative_months: int
    balanced_months: int
    insufficient_months: int
