"""Validated API request and response models."""
from __future__ import annotations

from datetime import date as DateType
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(min_length=1, max_length=160)]
PositiveArea = Annotated[float, Field(gt=0, le=1_000_000)]
NonnegativeMoney = Annotated[float, Field(ge=0, le=1_000_000_000)]
PositiveKg = Annotated[float, Field(gt=0, le=1_000_000_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FarmCreate(StrictModel):
    name: Name
    location: str | None = Field(default=None, max_length=240)
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    irrigation_efficiency: Annotated[float, Field(gt=0, le=1)] | None = None
    effective_rain_fraction: Annotated[float, Field(ge=0, le=1)] | None = None
    area_dunum: PositiveArea | None = None
    planting_date: DateType | None = None
    crop_stage: str | None = Field(default=None, max_length=40)
    irrigation_method: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class FarmPatch(StrictModel):
    name: Name | None = None
    location: str | None = Field(default=None, max_length=240)
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    irrigation_efficiency: Annotated[float, Field(gt=0, le=1)] | None = None
    effective_rain_fraction: Annotated[float, Field(ge=0, le=1)] | None = None
    area_dunum: PositiveArea | None = None
    planting_date: DateType | None = None
    crop_stage: str | None = Field(default=None, max_length=40)
    irrigation_method: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def coordinate_pair(self):
        fields = self.model_fields_set
        if ("latitude" in fields) != ("longitude" in fields):
            raise ValueError("latitude and longitude must be updated together")
        return self


class FarmRead(FarmCreate):
    id: str
    origin: str = Field(validation_alias="data_origin")
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SeasonCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    crop: str = Field(default="tomato", min_length=1, max_length=80)
    start_date: DateType | None = None
    end_date: DateType | None = None
    is_active: bool = True
    expected_harvest_kg: PositiveKg | None = None
    projected_costs_jod: NonnegativeMoney | None = None
    projected_revenue_jod: NonnegativeMoney | None = None
    fertilizer_budget_jod: NonnegativeMoney | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SeasonPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    crop: str | None = Field(default=None, min_length=1, max_length=80)
    start_date: DateType | None = None
    end_date: DateType | None = None
    is_active: bool | None = None
    expected_harvest_kg: PositiveKg | None = None
    projected_costs_jod: NonnegativeMoney | None = None
    projected_revenue_jod: NonnegativeMoney | None = None
    fertilizer_budget_jod: NonnegativeMoney | None = None


class SeasonRead(SeasonCreate):
    id: str
    farm_id: str
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class IrrigationCreate(StrictModel):
    date: DateType
    confirmed: bool = True
    season_id: str | None = None
    amount_mm: Annotated[float, Field(ge=0, le=10_000)] | None = None
    volume_m3: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    notes: str | None = Field(default=None, max_length=4000)


class IrrigationPatch(StrictModel):
    date: DateType | None = None
    confirmed: bool | None = None
    season_id: str | None = None
    amount_mm: Annotated[float, Field(ge=0, le=10_000)] | None = None
    volume_m3: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    notes: str | None = Field(default=None, max_length=4000)


class IrrigationRead(IrrigationCreate):
    id: str
    farm_id: str
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ExpenseCreate(StrictModel):
    date: DateType
    category: str = Field(min_length=1, max_length=80)
    amount_jod: NonnegativeMoney
    season_id: str | None = None
    description: str | None = Field(default=None, max_length=4000)


class ExpensePatch(StrictModel):
    date: DateType | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)
    amount_jod: NonnegativeMoney | None = None
    season_id: str | None = None
    description: str | None = Field(default=None, max_length=4000)


class ExpenseRead(ExpenseCreate):
    id: str
    farm_id: str
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class HarvestCreate(StrictModel):
    date: DateType
    quantity_kg: PositiveKg
    season_id: str | None = None
    grade: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)


class HarvestPatch(StrictModel):
    date: DateType | None = None
    quantity_kg: PositiveKg | None = None
    season_id: str | None = None
    grade: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)


class HarvestRead(HarvestCreate):
    id: str
    farm_id: str
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SaleCreate(StrictModel):
    date: DateType
    quantity_kg: PositiveKg
    unit_price_jod: NonnegativeMoney
    season_id: str | None = None
    harvest_id: str | None = None
    buyer: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)


class SalePatch(StrictModel):
    date: DateType | None = None
    quantity_kg: PositiveKg | None = None
    unit_price_jod: NonnegativeMoney | None = None
    season_id: str | None = None
    harvest_id: str | None = None
    buyer: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)


class SaleRead(SaleCreate):
    id: str
    farm_id: str
    total_jod: NonnegativeMoney
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class FinancialsRead(StrictModel):
    origin: str
    recorded_costs_jod: NonnegativeMoney | None
    projected_costs_jod: NonnegativeMoney | None
    actual_revenue_jod: NonnegativeMoney | None
    projected_revenue_jod: NonnegativeMoney | None
    fertilizer_budget_jod: NonnegativeMoney | None
    expected_harvest_kg: PositiveKg | None
    expected_harvest_source: str | None = None
    expected_harvest_scope: str | None = None
    actual_harvest_kg: NonnegativeMoney | None
    actual_harvest_source: str | None = None
    actual_harvest_scope: str | None = None
    actual_harvest_active_season_kg: NonnegativeMoney | None = None
    fertilizer_options: list[dict] = Field(default_factory=list)
    actual_sold_kg: NonnegativeMoney | None = None
    actual_cost_per_sold_kg_jod: NonnegativeMoney | None = None
    actual_break_even_jod_per_kg: NonnegativeMoney | None = None
    calculation_warnings: list[str] = Field(default_factory=list)


class AssistantChat(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="ar", pattern="^(ar|en)$")
    farm_id: str | None = Field(default=None, max_length=64)


class VoiceRequest(StrictModel):
    recommendation_id: str = Field(min_length=1, max_length=128)
    language: str = Field(default="ar-JO", pattern="^ar-JO$")
    voice_id: str = Field(default="ar-JO-TaimNeural", pattern="^ar-JO-TaimNeural$")
    farm_id: str | None = Field(default=None, max_length=64)

