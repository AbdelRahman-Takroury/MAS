"""Normalize weather advisories into conservative inspection states."""

from datetime import datetime, date, timedelta


INSPECTION_SOURCE = {
    "name": "Demonstration weather inspection rules",
    "reference": None,
    "retrieved_at": None,
}
EVIDENCE_LIMITATION = "Environmental conditions could not be fully assessed."
NO_DIAGNOSIS_WARNING = "Environmental favorability is not a disease diagnosis."


def _has_required_weather(weather: dict) -> bool:
    """Require temperature and humidity on every supplied forecast day."""
    daily = weather.get("daily")
    requested = weather.get("summary", {}).get("requested_days", 7)
    if not isinstance(daily, list) or len(daily) != requested:
        return False
    try:
        start = date.fromisoformat(weather["forecast_start_date"])
        if {row.get("date") for row in daily} != {(start + timedelta(days=i)).isoformat() for i in range(requested)}:
            return False
    except (KeyError, ValueError, TypeError):
        return False
    return all(
        isinstance(day, dict)
        and day.get("temperature_max_c") is not None
        and day.get("relative_humidity_mean_percent") is not None
        and day.get("relative_humidity_hours_available", 24) == day.get("relative_humidity_hours_expected", 24)
        for day in daily
    )


def normalize_inspection_state(weather: dict, generated_at: datetime) -> dict:
    """Return an inspection condition, never an infection probability.

    Salah's weather advisories are deterministic reminders. This wrapper only
    distinguishes an assessed trigger, an assessed no-trigger result, and an
    assessment that cannot be made because required evidence is absent.
    """
    weather_available = weather.get("status") in {"live", "cached"}
    if not weather_available or not _has_required_weather(weather):
        return {
            "status": "missing_data",
            "data_kind": "calculated",
            "source": INSPECTION_SOURCE,
            "generated_at": generated_at,
            "missing_inputs": ["temperature or humidity data"],
            "assumptions": [],
            "warnings": [],
            "assessment": "cannot_assess",
            "alerts": [],
            "inspection_actions": ["Continue routine field inspection."],
            "limitations": [EVIDENCE_LIMITATION],
        }

    advisories = weather.get("advisories")
    advisories = advisories if isinstance(advisories, list) else []
    alerts = []
    for advisory in advisories:
        if not isinstance(advisory, dict) or not advisory.get("message"):
            continue
        date = advisory.get("date")
        alert = f"{date}: {advisory['message']}" if date else str(advisory["message"])
        if alert not in alerts:
            alerts.append(alert)

    return {
        "status": "ok",
        "data_kind": "calculated",
        "source": INSPECTION_SOURCE,
        "generated_at": generated_at,
        "missing_inputs": [],
        "assumptions": [
            "Weather advisory thresholds are demonstration inspection heuristics."
        ],
        "warnings": [NO_DIAGNOSIS_WARNING],
        "assessment": "favorable" if alerts else "not_favorable",
        "alerts": alerts,
        "inspection_actions": ["Continue routine visual inspection of tomato plants."],
        "limitations": [
            "Outdoor weather does not measure canopy leaf wetness.",
            "This assessment does not establish whether plants are infected.",
        ],
    }
