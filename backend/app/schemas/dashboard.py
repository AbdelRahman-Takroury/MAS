"""Stable dashboard response contract consumed by the frontend."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .common import ModuleMetadata, StrictModel


class WeatherDay(StrictModel):
    date: date
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    precipitation_mm: float | None = Field(default=None, ge=0)
    relative_humidity_mean_percent: float | None = Field(default=None, ge=0, le=100)
    et0_mm: float | None = Field(default=None, ge=0)


class WeatherModule(ModuleMetadata):
    data_kind: Literal["live", "cached"] | None = None
    coverage_status: Literal["complete", "partial", "unavailable"] = "unavailable"
    coverage: dict = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)
    timezone: Literal["Asia/Amman"] = "Asia/Amman"
    forecast_generated_at: datetime | None = None
    daily: list[WeatherDay] = Field(default_factory=list)


class IrrigationModule(ModuleMetadata):
    period_days: int | None = Field(default=None, ge=1, le=7)
    period_start_date: date | None = None
    period_end_date: date | None = None
    water_required_liters: float | None = Field(default=None, ge=0)
    runtime_hours: float | None = Field(default=None, ge=0)
    calculator_version: str


class WaterBudgetModule(ModuleMetadata):
    water_required_liters: float | None = Field(default=None, ge=0)
    water_available_liters: float | None = Field(default=None, ge=0)
    allocation_liters: float | None = Field(default=None, ge=0)
    water_period_start: date | None = None
    water_period_end: date | None = None
    forecast_period_start: date | None = None
    forecast_period_end: date | None = None
    availability_source: Literal["user_entered", "seeded_demo", "simulated", "missing_data"] = "missing_data"
    water_shortage_liters: float | None = Field(default=None, ge=0)
    water_surplus_liters: float | None = Field(default=None, ge=0)
    coverage_percentage: float | None = Field(default=None, ge=0)
    water_status: Literal["sufficient", "shortage", "unavailable"]


class FinanceModule(ModuleMetadata):
    projected_total_cost_jod: float = Field(ge=0)
    expected_marketable_kg: float | None = Field(default=None, ge=0)
    break_even_jod_per_kg: float | None = Field(default=None, ge=0)
    assumed_sale_price_jod_per_kg: float | None = Field(default=None, ge=0)
    projected_revenue_jod: float | None = Field(default=None, ge=0)
    projected_profit_jod: float | None = None
    calculator_version: str


class InspectionModule(ModuleMetadata):
    assessment: Literal["favorable", "not_favorable", "cannot_assess"]
    alerts: list[str] = Field(default_factory=list)
    inspection_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DashboardResponse(StrictModel):
    farm_id: str
    generated_at: datetime
    is_sample: bool
    weather: WeatherModule
    irrigation: IrrigationModule
    water_budget: WaterBudgetModule
    finance: FinanceModule
    inspection: InspectionModule
    actions: list[str] = Field(default_factory=list)
