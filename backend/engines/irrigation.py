"""Pure open-field tomato water estimates from normalized Weather Engine output.

Decimal arithmetic is internal; finite JSON numbers are serialized without display
rounding. No HTTP/database/automatic irrigation. Explicit farm assumptions are
required. Full-period totals are withheld when any requested date/value is missing.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext
import math


FAO_KC_URL = "https://www.fao.org/4/X0490E/x0490e0b.htm"
AMMAN_TIME = timezone(timedelta(hours=3))
DEFAULT_KC = {"initial": Decimal("0.60"), "mid_season": Decimal("1.15"), "late_season": Decimal("0.80")}
STAGES = {"initial", "development", "mid_season", "late_season"}
TOTAL_FIELDS = {
    "total_etc_mm": "etc_mm",
    "total_crop_water_consumption_liters": "crop_water_consumption_liters",
    "total_effective_rain_mm": "effective_rain_mm",
    "total_net_irrigation_liters": "net_irrigation_liters",
    "total_gross_irrigation_liters": "gross_irrigation_liters",
    "total_runtime_hours": "runtime_hours",
}
ASSUMPTIONS = (
    "Crop stage/Kc is held constant over the assessed period; no crop calendar is inferred.",
    "ETc estimates crop consumption under reference coefficient assumptions, not measured field water use.",
    "Effective rain fraction and application efficiency are explicit caller assumptions, not validated drip-system properties.",
    "Excess rain is not transferred between days; soil storage, groundwater, runoff, salinity and drainage are not modelled.",
    "Volumes and runtime are planning estimates, not an exact irrigation schedule or continuous-run instruction.",
    "Confirmed past irrigation is not subtracted from future demand without a dated soil-water balance.",
)


def _now(reference_time: datetime | None = None) -> datetime:
    value = datetime.now(timezone.utc) if reference_time is None else reference_time
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reference_time: must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Expected a timezone-aware ISO timestamp")
    try:
        return _now(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError("Expected a timezone-aware ISO timestamp") from exc


def _date(value) -> date:
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    raise ValueError("Expected an ISO YYYY-MM-DD date")


def _number(value, path: str, *, positive=False, maximum=None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: must be a finite JSON number")
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{path}: must be finite and fit a JSON number")
    number = Decimal(str(value))
    if number < 0 or (positive and number == 0) or (maximum is not None and number > maximum):
        requirement = "positive" if positive else "nonnegative"
        raise ValueError(f"{path}: must be {requirement}" + (f" and <= {maximum}" if maximum is not None else ""))
    return number


def _json_number(value: Decimal | None):
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result) or (value != 0 and result == 0):
        raise ValueError("Derived result is outside the finite JSON number range; check input magnitudes")
    return result


def _context(numbers: list[Decimal]) -> Context:
    span = (max(max(n.adjusted() + 1, 1) for n in numbers)
            - min(min(n.as_tuple().exponent, 0) for n in numbers)) if numbers else 1
    return Context(prec=max(50, 4 * span + len(str(len(numbers))) + 20), Emax=MAX_EMAX, Emin=MIN_EMIN)


def _farm_inputs(farm: dict, kc_parameters: dict | None) -> tuple[dict, dict, list[str]]:
    if not isinstance(farm, dict):
        raise ValueError("farm: must be an object")
    for field in ("crop", "area_m2", "irrigation_method"):
        if field not in farm:
            raise ValueError(f"farm.{field}: required")
    if farm["crop"] != "tomato" or farm["irrigation_method"] != "drip":
        raise ValueError("Only crop=tomato and irrigation_method=drip are supported")
    inputs = {"area_m2": _number(farm["area_m2"], "farm.area_m2", positive=True)}
    for field in ("irrigation_efficiency", "effective_rain_fraction", "system_flow_liters_per_hour"):
        value = farm.get(field)
        inputs[field] = None if value is None else _number(
            value, "farm." + field, positive=field != "effective_rain_fraction",
            maximum=1 if field != "system_flow_liters_per_hour" else None,
        )
    stage = farm.get("crop_stage")
    if stage is not None and (not isinstance(stage, str) or stage not in STAGES):
        raise ValueError("farm.crop_stage: must be initial, development, mid_season, or late_season")
    configured = {}
    if kc_parameters is not None:
        if not isinstance(kc_parameters, dict) or set(kc_parameters) - STAGES:
            raise ValueError("kc_parameters: must map supported crop stages to positive coefficients")
        configured = {key: _number(value, f"kc_parameters.{key}", positive=True) for key, value in kc_parameters.items()}
    warnings = []
    override = farm.get("kc_override")
    if override is not None:
        kc = _number(override, "farm.kc_override", positive=True)
        source, explanation = "farmer_kc_override", "Explicit caller coefficient; not an independently verified farm calibration."
    else:
        if stage is None:
            raise ValueError("farm.crop_stage: required unless a valid kc_override is supplied")
        coefficients = {**DEFAULT_KC, **configured}
        if stage in configured:
            kc = configured[stage]
            source, explanation = "configured_stage_coefficient", "Explicit caller-configured stage coefficient."
        elif stage == "development":
            with localcontext(_context(list(coefficients.values()))):
                kc = (coefficients["initial"] + coefficients["mid_season"]) / Decimal("2")
            source, explanation = "development_midpoint_approximation", "Midpoint of initial and mid-season Kc; not a universal FAO development-stage coefficient."
            warnings.append(explanation)
        elif stage == "late_season":
            kc = coefficients[stage]
            source, explanation = "late_season_fixed_estimate", "Fixed 0.80 demonstration estimate within FAO tomato end-stage range 0.70-0.90; no continuous decline is modelled."
            warnings.append(explanation)
        else:
            kc = coefficients[stage]
            source, explanation = "fao56_table12_reference", "FAO-56 Table 12 reference coefficient; local climate/wetting adjustments are not modelled."
    inputs["kc"] = kc
    for field, message in (
        ("irrigation_efficiency", "Irrigation efficiency is unknown; gross irrigation and runtime are unavailable."),
        ("effective_rain_fraction", "Effective rain fraction is unknown; positive or missing rain cannot support a net estimate."),
        ("system_flow_liters_per_hour", "System flow is unknown; optional runtime estimates are unavailable."),
    ):
        if inputs[field] is None:
            warnings.append(message)
    metadata = {"value": _json_number(kc), "crop_stage": stage, "source": source,
                "source_url": FAO_KC_URL if source not in {"farmer_kc_override", "configured_stage_coefficient"} else None,
                "explanation": explanation}
    return inputs, metadata, warnings


def _weather_metadata(weather: dict, now: datetime, max_age_hours: Decimal) -> tuple[dict, list[str]]:
    if not isinstance(weather, dict):
        raise ValueError("weather: must be a normalized Weather Engine object")
    if (weather.get("status") not in ("live", "cached") or weather.get("source") != "open-meteo"
            or weather.get("data_type") != "forecast" or weather.get("timezone") != "Asia/Amman"
            or weather.get("synthetic") or weather.get("fixture_type")):
        raise ValueError("Weather is unavailable or lacks supported forecast provenance; synthetic data are not live forecasts")
    units = weather.get("units")
    if not isinstance(units, dict) or units.get("et0") != "mm/day" or units.get("precipitation") != "mm":
        raise ValueError("Weather units must specify et0=mm/day and precipitation=mm")
    retrieved = _parse_timestamp(weather.get("retrieved_at"))
    valid_until = retrieved + timedelta(hours=float(max_age_hours))
    if now < retrieved or now > valid_until:
        raise ValueError("Weather retrieval is future-dated or expired")
    start, end = _date(weather.get("forecast_start_date")), _date(weather.get("forecast_end_date"))
    count = (end - start).days + 1
    summary = weather.get("summary")
    if (not 1 <= count <= 7 or not isinstance(summary, dict)
            or type(summary.get("requested_days")) is not int or summary["requested_days"] != count):
        raise ValueError("Weather forecast dates and summary.requested_days must agree on a 1-7 day period")
    origin = retrieved.astimezone(AMMAN_TIME).date()
    # A cached adapter may extend its requested window after midnight, but cannot
    # invent observations beyond the original horizon; available rows are checked below.
    today = now.astimezone(AMMAN_TIME).date()
    if start < origin or start > today + timedelta(days=6) or end < today:
        raise ValueError("Weather forecast period is expired or outside its retrieval/current horizon")
    target_start = max(start, today)
    target_end = target_start + timedelta(days=count - 1)
    if target_end > today + timedelta(days=6):
        raise ValueError("Weather period extends beyond the current seven-day horizon")
    if not isinstance(weather.get("daily"), list):
        raise ValueError("Weather daily records must be a list")
    warnings = [str(item) for item in weather.get("warnings", [])] if isinstance(weather.get("warnings", []), list) else []
    if weather["status"] == "cached":
        warnings.append("Irrigation uses cached forecast data; original retrieval time and freshness limit are retained.")
    return {
        "status": weather["status"], "source": "open-meteo", "data_type": "forecast",
        "timezone": "Asia/Amman", "retrieved_at": _timestamp(retrieved), "valid_until": _timestamp(valid_until),
        "original_horizon_end": (origin + timedelta(days=6)).isoformat(),
        "forecast_start_date": start.isoformat(), "forecast_end_date": end.isoformat(),
        "period_start_date": target_start.isoformat(), "period_end_date": target_end.isoformat(),
        "requested_days": count,
    }, warnings


def _daily_inputs(weather: dict, metadata: dict, warnings: list[str]) -> list[dict]:
    start, end = _date(metadata["period_start_date"]), _date(metadata["period_end_date"])
    horizon = _date(metadata["original_horizon_end"])
    rows, seen = [], set()
    for index, record in enumerate(weather["daily"]):
        try:
            if not isinstance(record, dict):
                raise ValueError("record must be an object")
            day = _date(record.get("date"))
        except ValueError as exc:
            warnings.append(f"weather.daily[{index}] excluded: {exc}")
            continue
        if not start <= day <= end or day > horizon:
            warnings.append(f"{day}: expired/out-of-period forecast date excluded.")
            continue
        if day in seen:
            warnings.append(f"{day}: duplicate date excluded; missing period coverage is not invented.")
            continue
        seen.add(day)
        row = {"date": day.isoformat(), "warnings": []}
        for field in ("et0_mm", "precipitation_mm"):
            try:
                if record.get(field) is None:
                    raise ValueError(f"{field} is missing")
                row[field] = _number(record[field], f"{day}.{field}")
            except ValueError as exc:
                row[field] = None
                row["warnings"].append(str(exc) + "; dependent estimates are unavailable.")
        rows.append(row)
    return sorted(rows, key=lambda row: row["date"])


def _calculate_day(row: dict, inputs: dict) -> dict:
    et0, rain, kc = row["et0_mm"], row["precipitation_mm"], inputs["kc"]
    etc = et0 * kc if et0 is not None else None
    factor, efficiency, flow = (inputs[key] for key in ("effective_rain_fraction", "irrigation_efficiency", "system_flow_liters_per_hour"))
    effective_rain = Decimal("0") if rain == 0 else rain * factor if rain is not None and factor is not None else None
    net = max(etc - effective_rain, Decimal("0")) if etc is not None and effective_rain is not None else None
    net_liters = net * inputs["area_m2"] if net is not None else None
    gross = net_liters / efficiency if net_liters is not None and efficiency is not None else None
    warnings = list(row["warnings"])
    if effective_rain is None:
        warnings.append("Effective rainfall is unknown; net/gross irrigation are unavailable.")
    if efficiency is None:
        warnings.append("Explicit irrigation efficiency is required for gross supplied-water demand.")
    values = {
        "et0_mm": et0, "kc": kc, "etc_mm": etc,
        "crop_water_consumption_liters": etc * inputs["area_m2"] if etc is not None else None,
        "precipitation_mm": rain, "effective_rain_mm": effective_rain,
        "net_irrigation_mm": net, "net_irrigation_liters": net_liters,
        "gross_irrigation_liters": gross,
        "runtime_hours": gross / flow if gross is not None and flow is not None else None,
    }
    return {"date": row["date"], **values,
            "status": "calculated" if gross is not None else "partial" if etc is not None else "unavailable",
            "warnings": warnings}


def _summarize(rows: list[dict], days: int | None) -> dict:
    full_totals, partial_totals = {}, {}
    for total, field in TOTAL_FIELDS.items():
        covered = [row for row in rows if row[field] is not None]
        value = sum((row[field] for row in covered), Decimal("0")) if covered else None
        full = days is not None and len(covered) == days
        full_totals[total] = _json_number(value) if full else None
        partial_totals[total] = {
            "value": _json_number(value), "dates": [row["date"] for row in covered],
            "covered_days": len(covered), "requested_days": days,
            "status": "complete" if full else "partial" if covered else "unavailable",
        }
    complete_days = sum(row["gross_irrigation_liters"] is not None for row in rows)
    status = "calculated" if days is not None and complete_days == days else "partial" if any(row["etc_mm"] is not None for row in rows) else "unavailable"
    return {"status": status, "period_days": days, "available_days": len(rows), **full_totals,
            "complete_days": complete_days, "incomplete_days": days - complete_days if days is not None else None,
            "partial_totals": partial_totals}


def calculate_irrigation(
    farm: dict, weather: dict, *, kc_parameters: dict | None = None,
    reference_time: datetime | None = None, max_weather_age_hours=24.0,
) -> dict:
    """Estimate daily/period crop and supplied-water demand; never fetch weather.

    Caller farm/settings errors raise ValueError. Invalid/expired weather returns
    unavailable; bad/missing daily numbers withhold dependent values. Metadata
    and date coverage allow the water budget to recheck freshness independently.
    """
    now = _now(reference_time)
    max_age = _number(max_weather_age_hours, "max_weather_age_hours", maximum=168)
    inputs, coefficient, warnings = _farm_inputs(farm, kc_parameters)
    if not isinstance(weather, dict):
        raise ValueError("weather: must be a normalized Weather Engine object")
    try:
        metadata, weather_warnings = _weather_metadata(weather, now, max_age)
        warnings.extend(weather_warnings)
        rows = _daily_inputs(weather, metadata, warnings)
        days = metadata["requested_days"]
    except ValueError as exc:
        metadata, rows, days = None, [], None
        warnings.append("Weather unavailable: " + str(exc))
    numbers = [number for number in inputs.values() if number is not None]
    numbers.extend(row[key] for row in rows for key in ("et0_mm", "precipitation_mm") if row[key] is not None)
    with localcontext(_context(numbers)):
        calculated = [_calculate_day(row, inputs) for row in rows]
        summary = _summarize(calculated, days)
        daily = [{key: _json_number(value) if isinstance(value, Decimal) else value for key, value in row.items()} for row in calculated]
    if summary["status"] != "calculated":
        warnings.append("Full-period supplied-water demand is unavailable; partial totals identify only their covered dates.")
    return {
        "status": summary["status"], "data_type": "estimate", "calculated_at": _timestamp(now),
        "period_days": days, "period_start_date": metadata["period_start_date"] if metadata else None,
        "period_end_date": metadata["period_end_date"] if metadata else None,
        "weather_provenance": metadata, "kc": coefficient,
        "farm_assumptions": {key: _json_number(value) for key, value in inputs.items() if key != "kc"},
        "daily": daily, "summary": summary, "warnings": warnings, "assumptions": list(ASSUMPTIONS),
        "units": {"et0": "mm/day", "etc": "mm/day", "precipitation": "mm/day",
                  "effective_rain": "mm/day", "net_irrigation_depth": "mm/day", "volume": "liters",
                  "area": "m2", "runtime": "hours", "system_flow": "liters/hour", "kc": "dimensionless"},
    }


def summarize_irrigation_records(records: list[dict]) -> dict:
    """Sum confirmed records separately from planned/proposed events; no demand credit."""
    if not isinstance(records, list):
        raise ValueError("records: must be a list")
    parsed, seen = [], set()
    for index, row in enumerate(records):
        if not isinstance(row, dict) or not {"id", "date", "applied_liters", "status"} <= row.keys():
            raise ValueError(f"records[{index}]: id, date, applied_liters, and status are required")
        identifier = row["id"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip():
            raise ValueError(f"records[{index}].id: must be a nonblank unpadded string")
        if identifier in seen:
            raise ValueError(f"records[{index}]: duplicate id '{identifier}'")
        seen.add(identifier)
        if row["status"] not in ("confirmed", "planned", "proposed"):
            raise ValueError(f"records[{index}].status: must be confirmed, planned, or proposed")
        parsed.append({"id": identifier, "date": _date(row["date"]).isoformat(),
                       "applied_liters": _number(row["applied_liters"], f"records[{index}].applied_liters"),
                       "status": row["status"]})
    confirmed = [row for row in parsed if row["status"] == "confirmed"]
    pending = [row for row in parsed if row["status"] != "confirmed"]
    with localcontext(_context([row["applied_liters"] for row in parsed])):
        confirmed_total = sum((row["applied_liters"] for row in confirmed), Decimal("0"))
        pending_total = sum((row["applied_liters"] for row in pending), Decimal("0"))
    return {
        "status": "summarized", "confirmed_record_ids": [row["id"] for row in confirmed],
        "confirmed_applied_liters": _json_number(confirmed_total), "confirmed_count": len(confirmed),
        "unconfirmed_record_ids": [row["id"] for row in pending],
        "unconfirmed_proposed_liters": _json_number(pending_total), "unconfirmed_count": len(pending),
        "warnings": ["Reported confirmed volume does not prove crop root-zone needs were satisfied; no past volume is credited against future demand."],
    }
