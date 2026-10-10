"""Farm profile request and response contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .common import StrictModel


class FarmCreate(StrictModel):
    farm_id: str = Field(min_length=1, max_length=100)
    location_name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: Literal["Asia/Amman"] = "Asia/Amman"
    area_m2: float = Field(gt=0)
    crop: Literal["tomato"] = "tomato"
    establishment_date: date
    establishment_method: Literal["transplanted", "direct_seeded", "unknown"]
    crop_stage: Literal["initial", "development", "mid_season", "late_season"]
    irrigation_method: Literal["drip"] = "drip"
    irrigation_efficiency: float | None = Field(default=None, gt=0, le=1)
    effective_rain_fraction: float | None = Field(default=None, ge=0, le=1)
    system_flow_liters_per_hour: float | None = Field(default=None, gt=0)
    preferred_language: Literal["ar", "en"] = "ar"
    is_sample: bool = False


class FarmResponse(FarmCreate):
    plot_id: str
    crop_season_id: str
    created_at: datetime
    updated_at: datetime
