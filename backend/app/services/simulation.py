"""Non-persistent water and finance scenario integration."""

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.engines.water_budget import calculate_water_budget

from ..schemas.simulation import SimulationRequest, SimulationResponse
from .dashboard import (
    DEMO_AVAILABLE_WATER_LITERS,
    _calculation_context,
    _finance_module,
    _water_budget_module,
)


NO_YIELD_RESPONSE = "No yield response to water shortage was modeled."


def build_simulation(
    database: Session,
    farm_id: str,
    request: SimulationRequest,
) -> SimulationResponse:
    """Run explicit overrides without modifying any ORM entity."""
    farm, season, generated_at, _weather, irrigation = _calculation_context(
        database, farm_id
    )
    overrides = request.overrides
    water_available = (
        overrides.water_available_liters
        if overrides.water_available_liters is not None
        else DEMO_AVAILABLE_WATER_LITERS
    )
    water_result = calculate_water_budget(
        irrigation,
        water_available,
        reference_time=generated_at,
    )
    availability_assumption = (
        "Available water is a non-persistent scenario override for the forecast period."
        if overrides.water_available_liters is not None
        else "Available water retains the 4,000-liter dashboard demonstration assumption."
    )
    water_budget = _water_budget_module(
        water_result,
        generated_at,
        data_kind="simulated",
        availability_assumption=availability_assumption,
    )
    quantity = (
        Decimal(str(overrides.expected_marketable_kg))
        if overrides.expected_marketable_kg is not None
        else season.expected_marketable_kg
    )
    price = (
        Decimal(str(overrides.sale_price_jod_per_kg))
        if overrides.sale_price_jod_per_kg is not None
        else season.assumed_sale_price_jod_per_kg
    )
    additional_costs = Decimal(str(overrides.additional_costs_jod or 0))
    finance = _finance_module(
        season,
        generated_at,
        expected_marketable_kg=quantity,
        sale_price_jod_per_kg=price,
        additional_costs_jod=additional_costs,
        data_kind="simulated",
    )
    return SimulationResponse.model_validate(
        {
            "farm_id": farm.id,
            "generated_at": generated_at,
            "persisted": False,
            "water_budget": water_budget,
            "finance": finance,
            "unsupported_effects": [NO_YIELD_RESPONSE],
        }
    )
