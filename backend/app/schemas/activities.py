"""Expense and confirmed-irrigation API contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .common import StrictModel
from .precision import Money, Liters, Duration, Flow


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value


class ExpenseCreate(StrictModel):
    crop_season_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=50)
    amount_jod: Money
    incurred_at: datetime
    cost_view: Literal["cash", "full"] = "cash"
    idempotency_key: str = Field(min_length=1, max_length=150)

    _validate_timestamp = field_validator("incurred_at")(_require_aware)


class ExpenseResponse(ExpenseCreate):
    amount_jod: float = Field(ge=0)  # Preserve the public numeric JSON response.
    id: str
    created_at: datetime
    updated_at: datetime


class IrrigationCreate(StrictModel):
    crop_season_id: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    amount_liters: Liters
    duration_hours: Duration | None = None
    system_flow_liters_per_hour: Flow | None = None
    measurement_basis: Literal["measured", "calibrated", "estimated", "unknown"]
    idempotency_key: str = Field(min_length=1, max_length=150)

    _validate_timestamp = field_validator("occurred_at")(_require_aware)


class IrrigationResponse(IrrigationCreate):
    # Historical zero-volume rows remain readable; new writes must be positive.
    amount_liters: float = Field(ge=0)
    duration_hours: float | None = None
    system_flow_liters_per_hour: float | None = None
    id: str
    status: Literal["confirmed"] = "confirmed"
    created_at: datetime
    updated_at: datetime
