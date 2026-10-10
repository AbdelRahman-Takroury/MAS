"""Non-persistent what-if simulation contracts."""

from datetime import datetime

from pydantic import Field, model_validator

from .common import StrictModel
from .dashboard import FinanceModule, WaterBudgetModule


class SimulationOverrides(StrictModel):
    water_available_liters: float | None = Field(default=None, ge=0)
    expected_marketable_kg: float | None = Field(default=None, ge=0)
    sale_price_jod_per_kg: float | None = Field(default=None, ge=0)
    additional_costs_jod: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_at_least_one_override(self):
        if all(value is None for value in (
            self.water_available_liters,
            self.expected_marketable_kg,
            self.sale_price_jod_per_kg,
            self.additional_costs_jod,
        )):
            raise ValueError("At least one simulation override is required")
        return self


class SimulationRequest(StrictModel):
    overrides: SimulationOverrides


class SimulationResponse(StrictModel):
    farm_id: str
    generated_at: datetime
    persisted: bool = False
    water_budget: WaterBudgetModule
    finance: FinanceModule
    unsupported_effects: list[str] = Field(default_factory=list)
