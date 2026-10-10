"""Dashboard input contracts; strict canonical tomato/drip domain, no invented inputs."""
from datetime import date as Date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class FarmInput(Strict):
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)
    latitude: Decimal = Field(ge=-90, le=90, decimal_places=6)
    longitude: Decimal = Field(ge=-180, le=180, decimal_places=6)
    area_dunum: Quantity
    planting_date: Date
    crop_stage: Literal["initial", "development", "mid_season", "late_season"]
    irrigation_method: Literal["drip"] = "drip"
    establishment_method: Literal["transplanted", "direct_seeded", "unknown"] = "unknown"
    irrigation_efficiency: Decimal | None = Field(default=None, gt=0, le=1, decimal_places=5)
    effective_rain_fraction: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=5)
    system_flow_liters_per_hour: Quantity | None = None


class SeasonInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    crop: Literal["tomato"] = "tomato"
    start_date: Date
    end_date: Date | None = None
    is_active: bool = True
    expected_harvest_kg: Money | None = None
    projected_costs_jod: Money | None = None
    fertilizer_budget_jod: Money | None = None
    assumed_sale_price_jod_per_kg: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)

    @model_validator(mode="after")
    def dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class Record(Strict):
    date: Date
    season_id: str | None = Field(default=None, max_length=100)


class ExpenseInput(Record):
    amount_jod: Money
    category: str = Field(min_length=1, max_length=50)
    description: str = Field(default="Expense", min_length=1, max_length=300)


class IrrigationInput(Record):
    confirmed: Literal[True] = True
    volume_m3: Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=6)] | None = None
    amount_mm: Annotated[Decimal, Field(ge=0, le=10000, decimal_places=3)] | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def amount(self):
        if self.volume_m3 is None and self.amount_mm is None:
            raise ValueError("volume_m3 or amount_mm is required")
        return self


class HarvestInput(Record):
    quantity_kg: Quantity
    grade: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)


class SaleInput(Record):
    quantity_kg: Quantity
    unit_price_jod: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    harvest_id: str | None = Field(default=None, max_length=100)
    buyer: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)


class ChatInput(Strict):
    farm_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    language: Literal["ar", "en"] = "ar"


class VoiceInput(Strict):
    farm_id: str = Field(min_length=1, max_length=100)
    recommendation_id: str = Field(min_length=1, max_length=150)
    language: Literal["ar-JO"] = "ar-JO"
    voice_id: Literal["ar-JO-TaimNeural"] = "ar-JO-TaimNeural"
