"""Translate Salah's engine contracts into the stable dashboard contract."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.engines.finance_preparation import prepare_financials
from backend.engines.irrigation import calculate_irrigation
from backend.engines.water_budget import calculate_water_budget
from backend.services.weather import get_weather

from ..config import settings
from ..models import CropSeason, Farm, Plot
from ..schemas.dashboard import DashboardResponse
from .inspection import normalize_inspection_state
from .weather_metadata import farm_snapshot_path, coverage_metadata


IRRIGATION_VERSION = "irrigation-fao56-demo-v1"
FINANCE_VERSION = "finance-demo-v1"
_USE_PERSISTED = object()


def _source(name: str, reference: str | None = None, retrieved_at=None) -> dict:
    return {"name": name, "reference": reference, "retrieved_at": retrieved_at}


def _dashboard_status(engine_status: str) -> str:
    return {
        "calculated": "estimated",
        "partial": "missing_data",
        "unavailable": "unavailable",
    }.get(engine_status, "error")


def _active_farm(database: Session, farm_id: str) -> tuple[Farm, Plot, CropSeason]:
    farm = database.scalar(
        select(Farm)
        .options(
            selectinload(Farm.plots)
            .selectinload(Plot.crop_seasons)
            .selectinload(CropSeason.expenses)
        )
        .where(Farm.id == farm_id, Farm.owner_id == settings.demo_user_id)
    )
    if farm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found")
    for plot in farm.plots:
        season = next((item for item in plot.crop_seasons if item.is_active), None)
        if season is not None:
            return farm, plot, season
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Farm has no active crop season",
    )


def _weather_module(weather: dict, generated_at: datetime) -> dict:
    origin = weather.get("status")
    available = origin in {"live", "cached"}
    metadata = coverage_metadata(weather)
    days = [
        {
            "date": row["date"],
            "temperature_max_c": row.get("temperature_max_c"),
            "temperature_min_c": row.get("temperature_min_c"),
            "precipitation_mm": row.get("precipitation_mm"),
            "relative_humidity_mean_percent": row.get("relative_humidity_mean_percent"),
            "et0_mm": row.get("et0_mm"),
        }
        for row in weather.get("daily", [])
    ]
    return {
        "status": ("missing_data" if metadata["coverage_status"] != "complete" else "estimated" if origin == "cached" else "ok") if available else "unavailable",
        "data_kind": origin if available else None,
        **metadata,
        "errors": list(weather.get("errors", [])),
        "source": _source(
            "Open-Meteo",
            "https://open-meteo.com/",
            weather.get("retrieved_at"),
        ),
        "generated_at": generated_at,
        "assumptions": [],
        "warnings": list(weather.get("warnings", [])),
        "timezone": "Asia/Amman",
        "forecast_generated_at": weather.get("retrieved_at"),
        "daily": days,
    }


def _irrigation_module(result: dict, season: CropSeason, generated_at: datetime) -> dict:
    missing = []
    if result["status"] == "unavailable":
        missing.append("current weather forecast")
    if season.irrigation_efficiency is None:
        missing.append("irrigation_efficiency")
    if season.effective_rain_fraction is None:
        missing.append("effective_rain_fraction")
    if season.system_flow_liters_per_hour is None:
        missing.append("system_flow_liters_per_hour")
    summary = result["summary"]
    return {
        "status": _dashboard_status(result["status"]),
        "data_kind": "calculated",
        "source": _source(
            "FAO-56 demonstration baseline",
            result.get("kc", {}).get("source_url"),
        ),
        "generated_at": generated_at,
        "missing_inputs": missing,
        "assumptions": list(result.get("assumptions", [])),
        "warnings": list(result.get("warnings", [])),
        "period_days": result.get("period_days"),
        "period_start_date": result.get("period_start_date"),
        "period_end_date": result.get("period_end_date"),
        "water_required_liters": summary.get("total_gross_irrigation_liters"),
        "runtime_hours": summary.get("total_runtime_hours"),
        "calculator_version": IRRIGATION_VERSION,
    }


def _water_budget_module(
    result: dict,
    generated_at: datetime,
    *,
    data_kind: str = "calculated",
    availability_assumption: str | None = None,
) -> dict:
    missing = list(result.get("missing_inputs", []))
    if result.get("water_required_liters") is None:
        missing.append("water_required_liters")
    return {
        "status": _dashboard_status(result["status"]),
        "data_kind": data_kind,
        "source": _source("Zar3ati water-budget calculator"),
        "generated_at": generated_at,
        "missing_inputs": missing,
        "assumptions": [
            *result.get("assumptions", []),
            *([availability_assumption] if availability_assumption else []),
        ],
        "warnings": list(result.get("warnings", [])),
        "water_required_liters": result.get("water_required_liters"),
        "water_available_liters": result["water_available_liters"],
        "water_shortage_liters": result.get("water_shortage_liters"),
        "water_surplus_liters": result.get("water_surplus_liters"),
        "coverage_percentage": result.get("coverage_percentage"),
        "water_status": result.get("water_status", "unavailable"),
    }


def _finance_module(
    season: CropSeason,
    generated_at: datetime,
    *,
    expected_marketable_kg=_USE_PERSISTED,
    sale_price_jod_per_kg=_USE_PERSISTED,
    additional_costs_jod: Decimal = Decimal("0"),
    data_kind: str = "calculated",
) -> dict:
    recorded_costs = [
        {
            "id": expense.id,
            "description": expense.description,
            "amount_jod": str(expense.amount_jod),
        }
        for expense in sorted(season.expenses, key=lambda item: item.id)
    ]
    quantity = (
        season.expected_marketable_kg
        if expected_marketable_kg is _USE_PERSISTED
        else expected_marketable_kg
    )
    price = (
        season.assumed_sale_price_jod_per_kg
        if sale_price_jod_per_kg is _USE_PERSISTED
        else sale_price_jod_per_kg
    )
    projected_costs = []
    if season.projected_costs_jod:
        projected_costs.append({"id": f"{season.id}-remaining-costs", "description": "Expected remaining costs",
                                "amount_jod": str(season.projected_costs_jod)})
    if additional_costs_jod:
        projected_costs.append(
            {
                "id": f"{season.id}-scenario-additional-costs",
                "description": "Hypothetical additional scenario costs",
                "amount_jod": str(additional_costs_jod),
            }
        )
    future_sales = []
    if quantity is not None and quantity > 0:
        future_sales.append(
            {
                "id": f"{season.id}-expected-sale",
                "description": "Expected remaining marketable tomato harvest",
                "quantity_kg": str(quantity),
                "price_jod_per_kg": str(price) if price is not None else None,
            }
        )
    result = prepare_financials(
        {
            "recorded_costs": recorded_costs,
            "projected_costs": projected_costs,
            "actual_sales": [{"id": sale.id, "description": "Recorded tomato sale",
                              "quantity_kg": str(sale.quantity_kg), "revenue_jod": str(sale.quantity_kg * sale.unit_price_jod)}
                             for sale in season.sales],
            "future_sales": future_sales,
        }
    )["financials"]
    missing = []
    if quantity is None:
        missing.append("expected_marketable_kg")
    if price is None:
        missing.append("sale_price_jod_per_kg")
    engine_status = "partial" if missing else result["status"]
    assumptions = list(result["assumptions"])
    assumptions.append("Active-season expenses and actual sales are included. Expected quantity is remaining marketable harvest.")
    if additional_costs_jod:
        assumptions.append("Additional costs are a non-persistent scenario override.")
    return {
        "status": _dashboard_status(engine_status),
        "data_kind": data_kind,
        "source": _source("Zar3ati finance calculator"),
        "generated_at": generated_at,
        "missing_inputs": missing,
        "assumptions": assumptions,
        "warnings": list(result["warnings"]),
        "projected_total_cost_jod": float(Decimal(result["projected_total_costs_jod"])),
        "expected_marketable_kg": float(quantity) if quantity is not None else None,
        "break_even_jod_per_kg": (
            float(Decimal(result["break_even_price_jod_per_kg"]))
            if result["break_even_price_jod_per_kg"] is not None
            else None
        ),
        "assumed_sale_price_jod_per_kg": float(price) if price is not None else None,
        "projected_revenue_jod": (
            float(Decimal(result["projected_total_revenue_jod"]))
            if quantity is not None and price is not None
            else None
        ),
        "projected_profit_jod": (
            float(Decimal(result["projected_profit_jod"]))
            if quantity is not None and price is not None
            else None
        ),
        "calculator_version": FINANCE_VERSION,
    }


def _actions(irrigation: dict, budget: dict, finance: dict, weather: dict) -> list[str]:
    actions = []
    if weather["status"] == "unavailable":
        actions.append("Check weather availability before relying on a precise water estimate.")
    elif budget["water_status"] == "shortage":
        actions.append("Review available water against the estimated seven-day requirement.")
    if budget["water_available_liters"] is None:
        actions.append("Enter a water allocation with dates matching the forecast period.")
    if "system_flow_liters_per_hour" in irrigation["missing_inputs"]:
        actions.append("Confirm irrigation-system flow before requesting a runtime estimate.")
    if finance["missing_inputs"]:
        actions.append("Enter expected marketable harvest and an assumed selling price.")
    else:
        actions.append("Review the assumed selling price before making sales decisions.")
    return actions


def _farm_engine_inputs(plot: Plot, season: CropSeason) -> dict:
    return {
        "crop": season.crop,
        "area_m2": float(plot.area_m2),
        "crop_stage": season.crop_stage,
        "irrigation_method": season.irrigation_method,
        "irrigation_efficiency": (
            float(season.irrigation_efficiency)
            if season.irrigation_efficiency is not None
            else None
        ),
        "effective_rain_fraction": (
            float(season.effective_rain_fraction)
            if season.effective_rain_fraction is not None
            else None
        ),
        "system_flow_liters_per_hour": (
            float(season.system_flow_liters_per_hour)
            if season.system_flow_liters_per_hour is not None
            else None
        ),
    }


def _calculation_context(database: Session, farm_id: str):
    """Load persisted inputs and calculate the shared forecast demand once."""
    farm, plot, season = _active_farm(database, farm_id)
    weather_result = get_weather(
        float(farm.latitude),
        float(farm.longitude),
        timeout_seconds=3.0,
        snapshot_path=farm_snapshot_path(farm),
        save_snapshot=True,
    )
    # The engine rejects a forecast retrieved after its reference time. Capture
    # the shared calculation time only after the weather call completes.
    generated_at = datetime.now(timezone.utc)
    irrigation_result = calculate_irrigation(
        _farm_engine_inputs(plot, season),
        weather_result,
        reference_time=generated_at,
    )
    return farm, season, generated_at, weather_result, irrigation_result


def build_dashboard(database: Session, farm_id: str) -> DashboardResponse:
    """Load persisted inputs, run every engine, and normalize one dashboard."""
    farm, season, generated_at, weather_result, irrigation_result = _calculation_context(
        database, farm_id
    )
    budget = build_water_budget(season, irrigation_result, generated_at)
    weather = _weather_module(weather_result, generated_at)
    irrigation = _irrigation_module(irrigation_result, season, generated_at)
    finance = _finance_module(season, generated_at)
    inspection = normalize_inspection_state(weather_result, generated_at)
    return DashboardResponse.model_validate(
        {
            "farm_id": farm.id,
            "generated_at": generated_at,
            "is_sample": farm.is_sample,
            "weather": weather,
            "irrigation": irrigation,
            "water_budget": budget,
            "finance": finance,
            "inspection": inspection,
            "actions": _actions(irrigation, budget, finance, weather),
        }
    )


def build_water_budget(season, irrigation, generated_at, *, override=None, simulated=False):
    start, end = irrigation.get('period_start_date'), irrigation.get('period_end_date')
    allocation = float(season.water_available_liters) if season.water_available_liters is not None else None
    allocation_start = season.water_period_start.isoformat() if season.water_period_start else None
    allocation_end = season.water_period_end.isoformat() if season.water_period_end else None
    source = 'seeded_demo' if season.water_allocation_is_demo else 'user_entered'
    assumptions = []
    missing = []
    available = allocation
    if override is not None:
        available = float(override)
        allocation, allocation_start, allocation_end = available, start, end
        source = 'simulated'
        assumptions.append('Available water is a non-persistent scenario override for the forecast period.')
    elif available is None:
        source = 'missing_data'
        missing.append('water_available_liters')
    elif not start or not end or (allocation_start, allocation_end) != (start, end):
        available = None
        missing.append('water_allocation_matching_forecast_period')
        assumptions.append('Saved water allocation does not match the forecast period; no allocation was inferred or prorated.')
    if source == 'seeded_demo':
        assumptions.append('Saved seeded-demo water allocation; this is a demonstration value, not measured farm availability.')
    if available is None:
        result = {'status': 'partial', 'water_required_liters': irrigation['summary'].get('total_gross_irrigation_liters'),
                  'water_available_liters': None, 'water_status': 'unavailable', 'missing_inputs': missing}
    else:
        result = calculate_water_budget(irrigation, available, reference_time=generated_at,
                                        water_period_start_date=start, water_period_end_date=end)
    result.setdefault('assumptions', []).extend(assumptions)
    budget = _water_budget_module(result, generated_at, data_kind='simulated' if simulated else 'calculated')
    budget.update(allocation_liters=allocation, water_period_start=allocation_start, water_period_end=allocation_end,
                  forecast_period_start=start, forecast_period_end=end, availability_source=source)
    return budget
