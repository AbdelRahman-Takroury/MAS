"""Pure comparison of period-aligned available water and estimated gross demand."""

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
import math

from .irrigation import AMMAN_TIME, _context, _date, _json_number, _now, _number, _parse_timestamp


def _comparison(required: Decimal, available: Decimal) -> dict:
    coverage = min(available / required * Decimal("100"), Decimal("100")) if required else Decimal("100")
    shortage, surplus = max(required - available, Decimal("0")), max(available - required, Decimal("0"))
    return {
        "water_required_liters": _json_number(required), "water_available_liters": _json_number(available),
        "water_shortage_liters": _json_number(shortage), "water_surplus_liters": _json_number(surplus),
        "coverage_percentage": _json_number(coverage), "water_status": "shortage" if shortage else "sufficient",
        "indicator": (f"Estimated water shortage: {_json_number(shortage):g} liters over the assessed period."
                      if shortage else "Available water covers 100% of estimated gross irrigation demand over the assessed period."),
    }


def calculate_water_budget(
    irrigation_result: dict, water_available_liters: float, *, reference_time: datetime | None = None,
    water_period_start_date: str | None = None, water_period_end_date: str | None = None,
) -> dict:
    """Compare only a complete, fresh gross-demand period at the top level.

    With partial demand, top-level comparison metrics are None; a separately
    labelled partial_assessment compares ONLY known dates and never establishes
    full-period sufficiency. Availability is assumed to apply to the same period
    unless explicit matching water-period dates are supplied. No crop-loss model.
    """
    now = _now(reference_time)
    available = _number(water_available_liters, "water_available_liters")
    if not isinstance(irrigation_result, dict):
        raise ValueError("irrigation_result: must be an object")
    if irrigation_result.get("status") not in ("calculated", "partial", "unavailable"):
        raise ValueError("irrigation_result.status: invalid")
    warnings = []
    assumptions = [
        "Available water refers to the SAME upcoming period as estimated gross irrigation demand; scalar availability alone cannot verify this.",
        "Surplus is an arithmetic excess over estimated demand, not a guarantee of storage or delivery capacity.",
        "Water sufficiency does not guarantee crop safety or quantify crop stress/yield loss.",
        "Zero required volume uses 100% coverage by convention; no division by zero is performed.",
    ]
    result = {
        "status": "unavailable", "period_days": irrigation_result.get("period_days"),
        "period_start_date": irrigation_result.get("period_start_date"),
        "period_end_date": irrigation_result.get("period_end_date"),
        "weather_provenance": irrigation_result.get("weather_provenance"),
        "water_required_liters": None, "water_available_liters": _json_number(available),
        "water_shortage_liters": None, "water_surplus_liters": None, "coverage_percentage": None,
        "water_status": "unavailable", "indicator": "Insufficient information to calculate water sufficiency.",
        "partial_assessment": None, "warnings": warnings, "assumptions": assumptions,
        "units": {"volume": "liters", "coverage": "percent"},
    }
    if (water_period_start_date is None) != (water_period_end_date is None):
        raise ValueError("Both water-period dates must be supplied together")
    if water_period_start_date is not None:
        water_start, water_end = _date(water_period_start_date), _date(water_period_end_date)
        if (water_start.isoformat(), water_end.isoformat()) != (result["period_start_date"], result["period_end_date"]):
            raise ValueError("Available-water period does not match the irrigation forecast period")
    else:
        warnings.append("Available-water period was not independently supplied; caller must verify it matches the assessed forecast period.")
    if irrigation_result["status"] == "unavailable":
        warnings.append("Irrigation demand is unavailable; no water sufficiency comparison was made.")
        return result
    try:
        start, end = _date(result["period_start_date"]), _date(result["period_end_date"])
        days = result["period_days"]
        if type(days) is not int or not 1 <= days <= 7 or (end - start).days + 1 != days:
            raise ValueError("Irrigation period dates and period_days do not agree")
        today = now.astimezone(AMMAN_TIME).date()
        if start < today or end > today + timedelta(days=6):
            raise ValueError("Irrigation period is expired or outside the current seven-day horizon")
        provenance = irrigation_result.get("weather_provenance")
        if (not isinstance(provenance, dict) or provenance.get("status") not in ("live", "cached")
                or provenance.get("source") != "open-meteo" or provenance.get("data_type") != "forecast"
                or provenance.get("timezone") != "Asia/Amman"):
            raise ValueError("Missing supported weather provenance")
        retrieved = _parse_timestamp(provenance.get("retrieved_at"))
        valid_until = _parse_timestamp(provenance.get("valid_until"))
        if retrieved > now or valid_until < now or not timedelta(0) <= valid_until - retrieved <= timedelta(hours=168):
            raise ValueError("Weather provenance is expired, future-dated, or has an invalid freshness limit")
        if (provenance.get("period_start_date"), provenance.get("period_end_date"), provenance.get("requested_days")) != (start.isoformat(), end.isoformat(), days):
            raise ValueError("Irrigation period does not match weather-provenance coverage")
        original_end = retrieved.astimezone(AMMAN_TIME).date() + timedelta(days=6)
        units = irrigation_result.get("units")
        if not isinstance(units, dict) or units.get("volume") != "liters":
            raise ValueError("Irrigation volume units must be liters")
        daily = irrigation_result.get("daily")
        if not isinstance(daily, list):
            raise ValueError("Irrigation daily breakdown is missing")
        expected = {(start + timedelta(days=i)).isoformat() for i in range(days)}
        seen, known = set(), []
        for row in daily:
            if not isinstance(row, dict):
                raise ValueError("Invalid daily irrigation record")
            day = _date(row.get("date")).isoformat()
            if day not in expected or day in seen or _date(day) > original_end:
                raise ValueError("Daily irrigation dates are duplicated or do not match the forecast period")
            seen.add(day)
            if row.get("gross_irrigation_liters") is not None:
                known.append((day, _number(row["gross_irrigation_liters"], f"{day}.gross_irrigation_liters")))
        summary = irrigation_result.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("Irrigation summary is missing")
        total = summary.get("total_gross_irrigation_liters")
        required = _number(total, "total_gross_irrigation_liters") if total is not None else None
    except ValueError as exc:
        warnings.append(str(exc) + "; no comparison was made.")
        return result
    with localcontext(_context([available] + [volume for _, volume in known] + ([required] if required is not None else []))):
        subtotal = sum((volume for _, volume in known), Decimal("0"))
        full = len(known) == days and seen == expected and required is not None
        if full and not math.isclose(float(required), float(subtotal), rel_tol=1e-12, abs_tol=1e-9):
            warnings.append("Gross period total disagrees with the daily breakdown; no comparison was made.")
            return result
        if full:
            result.update(_comparison(required, available))
            result["status"] = "calculated"
        else:
            result["status"] = "partial"
            warnings.append("Gross demand does not cover the complete requested period; full-period sufficiency is unavailable.")
            if known:
                result["partial_assessment"] = {
                    "scope": "known_dates_only", "covered_dates": [day for day, _ in known],
                    "covered_days": len(known), "requested_days": days,
                    **_comparison(subtotal, available),
                    "warning": "Subset comparison only; remaining demand is unknown and available water is shared across the full period.",
                }
    if provenance["status"] == "cached":
        warnings.append("Budget uses cached forecast-derived demand; original retrieval timestamp is retained.")
    return result
