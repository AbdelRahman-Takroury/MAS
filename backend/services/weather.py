"""Open-Meteo seven-day forecasts for caller-supplied WGS84 coordinates.

Python 3.10+, standard library only. Weather numbers are JSON numbers, not money.
Dates/humidity use Asia/Amman's current UTC+03:00 offset, verified against provider
metadata. Forecasts are model estimates, never observations. Snapshot input must
be trusted server-owned data; provenance labels alone cannot authenticate a file.
See docs/member3/weather_integration.md for response and fallback contracts.
"""

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import socket
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Amman"
AMMAN_OFFSET_SECONDS = 10800
AMMAN_TIME = timezone(timedelta(seconds=AMMAN_OFFSET_SECONDS))
FORECAST_DAYS = 7
DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[2] / "data/sample_weather.json"
DEFAULT_THRESHOLDS = {"rain_mm": 5.0, "heat_c": 35.0, "wind_kmh": 30.0}
UNITS = {
    "temperature": "celsius", "precipitation": "mm", "wind_speed": "km/h",
    "et0": "mm/day", "relative_humidity": "percent",
    "rain_probability": "percent", "weather_code": "WMO",
}
# API key: (normalized key, expected API unit, lower bound, upper bound)
DAILY_FIELDS = {
    "temperature_2m_max": ("temperature_max_c", "°C", None, None),
    "temperature_2m_min": ("temperature_min_c", "°C", None, None),
    "precipitation_sum": ("precipitation_mm", "mm", 0, None),
    "precipitation_probability_max": ("rain_probability_max_percent", "%", 0, 100),
    "wind_speed_10m_max": ("wind_speed_max_kmh", "km/h", 0, None),
    "et0_fao_evapotranspiration": ("et0_mm", "mm", 0, None),
    "weather_code": ("weather_code", "wmo code", 0, None),
}
WMO_CODES = {0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
             71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}


class WeatherDataError(ValueError):
    """A provider/snapshot response cannot safely be interpreted as a forecast."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise WeatherDataError("retrieved_at must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("missing timezone")
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise WeatherDataError("retrieved_at must be a timezone-aware ISO timestamp") from exc


def _finite_number(value, name: str, lower=None, upper=None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name}: must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name}: must be a finite number")
    if (lower is not None and number < lower) or (upper is not None and number > upper):
        raise ValueError(f"{name}: outside allowed range [{lower}, {upper}]")
    return number


def _thresholds(rain_mm, heat_c, wind_kmh) -> dict:
    return {
        "rain_mm": _finite_number(rain_mm, "rain_threshold_mm", 0),
        "heat_c": _finite_number(heat_c, "heat_threshold_c"),
        "wind_kmh": _finite_number(wind_kmh, "wind_threshold_kmh", 0),
    }


def build_weather_url(latitude, longitude) -> str:
    """Validate numeric coordinates and construct the official forecast request."""
    latitude = _finite_number(latitude, "latitude", -90, 90)
    longitude = _finite_number(longitude, "longitude", -180, 180)
    return API_URL + "?" + urlencode({
        "latitude": latitude, "longitude": longitude,
        "daily": ",".join(DAILY_FIELDS), "hourly": "relative_humidity_2m",
        "timezone": TIMEZONE, "forecast_days": FORECAST_DAYS,
        "temperature_unit": "celsius", "wind_speed_unit": "kmh",
        "precipitation_unit": "mm", "timeformat": "iso8601",
    })


def _fetch_weather(url: str, timeout_seconds: float) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "SmartFarmAI/1.0"})
    with urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise WeatherDataError(f"HTTP {response.status}")
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeatherDataError("Provider returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise WeatherDataError("Provider returned an error or a non-object response")
    return payload


def _iso_date(value) -> date:
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    raise WeatherDataError("Invalid ISO YYYY-MM-DD forecast date")


def _array(block: dict, field: str, expected_length: int, warnings: list[str]) -> list:
    values = block.get(field)
    if not isinstance(values, list):
        warnings.append(f"{field}: missing or invalid array; values are unavailable.")
        return []
    if len(values) != expected_length:
        warnings.append(f"{field}: array length {len(values)} differs from time length {expected_length}; missing values stay null.")
    return values


def _value(values: list, index: int, name: str, warnings: list[str], lower=None, upper=None):
    value = values[index] if index < len(values) else None
    if value is None:
        warnings.append(f"{name}: unavailable.")
        return None
    try:
        return _finite_number(value, name, lower, upper)
    except ValueError as exc:
        warnings.append(str(exc) + "; value is unavailable.")
        return None


def aggregate_daily_humidity(payload: dict, dates: list[str], warnings: list[str]) -> dict:
    """Mean valid hourly percentages by returned local date; expose 24-hour coverage."""
    groups = {day: [] for day in dates}
    hourly = payload.get("hourly")
    units = payload.get("hourly_units")
    if not isinstance(hourly, dict) or not isinstance(units, dict) or units.get("relative_humidity_2m") != "%":
        warnings.append("Hourly humidity or its percent units are missing/invalid; daily means remain null.")
    elif units.get("time") != "iso8601":
        warnings.append("Hourly time units are not iso8601; humidity is unavailable.")
    else:
        times = hourly.get("time")
        if not isinstance(times, list):
            warnings.append("Hourly humidity time array is missing/invalid.")
        else:
            values = _array(hourly, "relative_humidity_2m", len(times), warnings)
            seen = set()
            for index, text in enumerate(times):
                try:
                    parsed = datetime.fromisoformat(text) if isinstance(text, str) else None
                    if (parsed is None or parsed.tzinfo is not None or parsed.minute != 0 or parsed.second != 0
                            or parsed.isoformat(timespec="minutes") != text):
                        raise ValueError("not a local whole-hour timestamp")
                except ValueError:
                    warnings.append(f"hourly.time[{index}]: invalid local hourly timestamp; excluded.")
                    continue
                if text in seen:
                    warnings.append(f"hourly.time[{index}]: duplicate hour; excluded.")
                    continue
                seen.add(text)
                day = parsed.date().isoformat()
                if day in groups:
                    value = _value(values, index, f"humidity[{text}]", warnings, 0, 100)
                    if value is not None:
                        groups[day].append(value)
    result = {}
    for day, values in groups.items():
        result[day] = {
            "relative_humidity_mean_percent": math.fsum(values) / len(values) if values else None,
            "relative_humidity_hours_available": len(values),
            "relative_humidity_hours_expected": 24,
        }
        if len(values) != 24:
            warnings.append(f"{day}: humidity coverage {len(values)}/24 hours; mean is partial or unavailable.")
    return result


def generate_weather_advisories(
    daily: list[dict], *, rain_threshold_mm=5.0, heat_threshold_c=35.0, wind_threshold_kmh=30.0,
) -> list[dict]:
    """Strictly-above-threshold demonstration reminders; no irrigation prescription."""
    limits = _thresholds(rain_threshold_mm, heat_threshold_c, wind_threshold_kmh)
    rules = (
        ("precipitation_mm", "rain_mm", "rain_irrigation_review", "Rainfall is forecast. Review your irrigation schedule and check actual soil moisture."),
        ("temperature_max_c", "heat_c", "heat_inspection", "High temperatures are forecast. Inspect tomato plants and verify soil moisture."),
        ("wind_speed_max_kmh", "wind_kmh", "wind_inspection", "Strong winds are forecast. Inspect exposed plants and field conditions."),
    )
    advisories = []
    for day in daily:
        for metric, threshold, kind, message in rules:
            value = day.get(metric)
            if value is not None and value > limits[threshold]:
                advisories.append({"date": day["date"], "type": kind, "metric": metric,
                                   "value": value, "threshold": limits[threshold], "message": message})
    return advisories


def summarize_weather(
    daily: list[dict], *, rain_threshold_mm=5.0, heat_threshold_c=35.0, wind_threshold_kmh=30.0,
) -> dict:
    """Aggregate supplied normalized days; label subset totals/counts explicitly."""
    limits = _thresholds(rain_threshold_mm, heat_threshold_c, wind_threshold_kmh)
    fields = [spec[0] for spec in DAILY_FIELDS.values()] + ["relative_humidity_mean_percent"]
    coverage = {field: sum(day.get(field) is not None for day in daily) for field in fields}
    metrics = {
        "total_precipitation_mm": ("precipitation_mm", None),
        "total_et0_mm": ("et0_mm", None),
        "heat_days": ("temperature_max_c", limits["heat_c"]),
        "wind_days": ("wind_speed_max_kmh", limits["wind_kmh"]),
        "rainy_days": ("precipitation_mm", 0.0),
    }
    values, statuses, counts = {}, {}, {}
    for key, (field, threshold) in metrics.items():
        available = [day[field] for day in daily if day.get(field) is not None]
        counts[key] = len(available)
        statuses[key] = "complete" if len(available) == FORECAST_DAYS else "partial" if available else "unavailable"
        if not available:
            values[key] = None
        elif threshold is not None:
            values[key] = sum(value > threshold for value in available)
        else:
            try:
                values[key] = math.fsum(available)
            except OverflowError:
                values[key] = None
                statuses[key] = "unavailable"
    complete = (len(daily) == FORECAST_DAYS and all(count == FORECAST_DAYS for count in coverage.values())
                and all(day.get("relative_humidity_hours_available") == 24 for day in daily)
                and all(status == "complete" for status in statuses.values()))
    return {
        "status": "complete" if complete else "partial" if any(coverage.values()) else "unavailable",
        "requested_days": FORECAST_DAYS, "available_days": len(daily),
        **values, "metric_status": statuses, "available_days_per_metric": counts,
        "available_days_per_field": coverage,
        "humidity_hours_available": sum(day.get("relative_humidity_hours_available", 0) for day in daily),
        "humidity_hours_expected": FORECAST_DAYS * 24,
        "thresholds": {**limits, "rainy_day_mm": 0.0},
    }


def normalize_weather_response(
    payload: dict, latitude, longitude, retrieved_at: str, *, reference_time: datetime | None = None,
    rain_threshold_mm=5.0, heat_threshold_c=35.0, wind_threshold_kmh=30.0,
) -> dict:
    """Validate raw provider JSON and normalize only current requested-period dates.

    Missing arrays/nulls become unavailable values with warnings; explicit wrong
    daily units or missing valid dates reject the response. reference_time is an
    aware datetime for deterministic normalization/cache checks, not an API setting.
    """
    latitude = _finite_number(latitude, "latitude", -90, 90)
    longitude = _finite_number(longitude, "longitude", -180, 180)
    retrieved = _parse_timestamp(retrieved_at)
    now = reference_time if reference_time is not None else retrieved
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("reference_time must be a timezone-aware datetime")
    if not isinstance(payload, dict) or payload.get("error"):
        raise WeatherDataError("Provider response is not a forecast object")
    if payload.get("data_type", "forecast") != "forecast" or payload.get("synthetic", False):
        raise WeatherDataError("Synthetic/non-forecast data cannot be presented as a live forecast")
    if payload.get("timezone") != TIMEZONE or payload.get("utc_offset_seconds") != AMMAN_OFFSET_SECONDS:
        raise WeatherDataError("Unexpected timezone/UTC offset; cannot safely interpret local forecast dates")
    daily = payload.get("daily")
    units = payload.get("daily_units")
    if not isinstance(daily, dict) or not isinstance(units, dict):
        raise WeatherDataError("Missing daily data or daily units")
    times = daily.get("time")
    if not isinstance(times, list) or not times or units.get("time") != "iso8601":
        raise WeatherDataError("Missing daily ISO date array or unexpected date units")
    warnings = ["Advisory thresholds are demonstration heuristics, not validated tomato risk thresholds."]
    arrays = {}
    for field, (_, expected_unit, _, _) in DAILY_FIELDS.items():
        if field in units and units[field] != expected_unit:
            raise WeatherDataError(f"Unexpected units for {field}: expected {expected_unit}")
        arrays[field] = _array(daily, field, len(times), warnings) if field in units else []
        if field not in units:
            warnings.append(f"{field}: units missing; values are unavailable.")
    today = now.astimezone(AMMAN_TIME).date()
    expected_dates = {(today + timedelta(days=i)).isoformat() for i in range(FORECAST_DAYS)}
    records, seen = [], set()
    for index, text in enumerate(times):
        try:
            day = _iso_date(text).isoformat()
        except WeatherDataError:
            warnings.append(f"daily.time[{index}]: invalid date; excluded.")
            continue
        if day not in expected_dates:
            warnings.append(f"{day}: outside current seven-day forecast period; excluded.")
            continue
        if day in seen:
            warnings.append(f"{day}: duplicate daily date; excluded.")
            continue
        seen.add(day)
        row = {"date": day}
        for field, (key, _, lower, upper) in DAILY_FIELDS.items():
            value = _value(arrays[field], index, f"{day}.{field}", warnings, lower, upper)
            if key == "weather_code" and value is not None:
                if not value.is_integer():
                    warnings.append(f"{day}: weather_code is not an integer; unavailable.")
                    value = None
                else:
                    value = int(value)
                    if value not in WMO_CODES:
                        warnings.append(f"{day}: unknown WMO code {value}; preserved without an invented label.")
            row[key] = value
        high, low = row["temperature_max_c"], row["temperature_min_c"]
        if high is not None and low is not None and low > high:
            warnings.append(f"{day}: minimum temperature exceeds maximum; both are unavailable.")
            row["temperature_max_c"] = row["temperature_min_c"] = None
        records.append(row)
    if not records:
        raise WeatherDataError("No valid dates in the current seven-day forecast period")
    records.sort(key=lambda row: row["date"])
    humidity = aggregate_daily_humidity(payload, [row["date"] for row in records], warnings)
    for row in records:
        row.update(humidity[row["date"]])
    settings = {"rain_threshold_mm": rain_threshold_mm, "heat_threshold_c": heat_threshold_c,
                "wind_threshold_kmh": wind_threshold_kmh}
    summary = summarize_weather(records, **settings)
    if summary["status"] != "complete":
        warnings.append("Forecast coverage is incomplete; inspect summary metric statuses and per-field coverage before downstream use.")
    for key, value in summary["metric_status"].items():
        if value == "unavailable":
            warnings.append(f"Summary {key} is unavailable; missing values are not treated as zero.")
    provider_coords = {}
    for key, lower, upper in (("latitude", -90, 90), ("longitude", -180, 180)):
        try:
            provider_coords["provider_" + key] = _finite_number(payload.get(key), "provider_" + key, lower, upper)
        except ValueError:
            provider_coords["provider_" + key] = None
            warnings.append(f"Provider {key} missing/invalid; requested coordinate is retained separately.")
    return {
        "status": "live", "source": "open-meteo", "data_type": "forecast",
        "retrieved_at": _timestamp(retrieved), "timezone": TIMEZONE,
        "latitude": latitude, "longitude": longitude, **provider_coords,
        "forecast_start_date": today.isoformat(),
        "forecast_end_date": (today + timedelta(days=FORECAST_DAYS - 1)).isoformat(),
        "daily": records, "summary": summary,
        "advisories": generate_weather_advisories(records, **settings),
        "warnings": warnings, "units": dict(UNITS), "errors": [],
    }


def _load_snapshot(path: Path, latitude: float, longitude: float, now: datetime, max_age_hours: float, settings: dict) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeatherDataError("Snapshot missing, unreadable, or invalid JSON") from exc
    if (not isinstance(saved, dict) or saved.get("snapshot_version") != 1
            or saved.get("source") != "open-meteo" or saved.get("data_type") != "forecast"):
        raise WeatherDataError("Snapshot lacks trusted forecast provenance; synthetic/demo data are not usable")
    for key, requested, lower, upper in (("latitude", latitude, -90, 90), ("longitude", longitude, -180, 180)):
        try:
            coordinate = _finite_number(saved.get(key), "snapshot." + key, lower, upper)
        except ValueError as exc:
            raise WeatherDataError(str(exc)) from exc
        if abs(coordinate - requested) > 0.000001:
            raise WeatherDataError("Snapshot coordinates do not match the requested farm")
    retrieved = _parse_timestamp(saved.get("retrieved_at"))
    age = now - retrieved
    if age.total_seconds() < 0 or age > timedelta(hours=max_age_hours):
        raise WeatherDataError("Snapshot retrieval timestamp is future-dated or stale")
    payload = saved.get("api_response")
    origin_date = retrieved.astimezone(AMMAN_TIME).date()
    try:
        dates = payload["daily"]["time"]
        if not isinstance(dates, list) or not dates:
            raise ValueError("missing dates")
        if any(not origin_date <= _iso_date(day) <= origin_date + timedelta(days=6) for day in dates):
            raise ValueError("dates outside original forecast period")
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherDataError("Snapshot dates do not match its original retrieval period") from exc
    result = normalize_weather_response(payload, latitude, longitude, saved["retrieved_at"], reference_time=now, **settings)
    if result["summary"]["status"] == "unavailable":
        raise WeatherDataError("Snapshot has no usable weather variables")
    result["status"] = "cached"
    result["warnings"].append("Cached forecast: original retrieval timestamp retained; past dates have been excluded.")
    return result


def _save_snapshot(path: Path, payload: dict, result: dict, request_url: str) -> None:
    """Atomically save only a fully validated live retrieval, never partial data."""
    if result["status"] != "live" or result["summary"]["status"] != "complete":
        raise WeatherDataError("Incomplete forecast was not saved; existing snapshot is preserved")
    daily, hourly = payload["daily"], payload["hourly"]
    if (daily["time"] != [day["date"] for day in result["daily"]]
            or any(len(daily[field]) != FORECAST_DAYS for field in DAILY_FIELDS)
            or len(hourly["time"]) != FORECAST_DAYS * 24
            or len(hourly["relative_humidity_2m"]) != FORECAST_DAYS * 24):
        raise WeatherDataError("Inconsistent raw arrays were not saved; existing snapshot is preserved")
    saved = {
        "snapshot_version": 1, "source": "open-meteo", "data_type": "forecast",
        "retrieved_at": result["retrieved_at"], "latitude": result["latitude"], "longitude": result["longitude"],
        "request_url": request_url, "api_response": payload,
    }
    text = json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix="weather-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _unavailable(latitude: float, longitude: float, errors: list[dict], settings: dict) -> dict:
    return {
        "status": "unavailable", "source": "open-meteo", "data_type": "forecast",
        "retrieved_at": None, "timezone": TIMEZONE, "latitude": latitude, "longitude": longitude,
        "provider_latitude": None, "provider_longitude": None,
        "forecast_start_date": None, "forecast_end_date": None,
        "daily": [], "summary": summarize_weather([], **settings), "advisories": [],
        "warnings": ["No usable current weather forecast; do not supply missing values to irrigation calculations."],
        "units": dict(UNITS), "errors": errors,
    }


def get_weather(
    latitude, longitude, *, timeout_seconds=10.0, snapshot_path=DEFAULT_SNAPSHOT,
    cache_max_age_hours=24.0, save_snapshot=False,
    rain_threshold_mm=5.0, heat_threshold_c=35.0, wind_threshold_kmh=30.0,
) -> dict:
    """Attempt one live request, then optional validated saved-response fallback.

    Invalid caller inputs raise ValueError before HTTP. Retrieval/response/cache
    failures return structured errors with status cached or unavailable. live does
    not mean complete: inspect summary.status. Saving is opt-in and atomic.
    """
    latitude = _finite_number(latitude, "latitude", -90, 90)
    longitude = _finite_number(longitude, "longitude", -180, 180)
    timeout = _finite_number(timeout_seconds, "timeout_seconds", 0, 60)
    if timeout == 0:
        raise ValueError("timeout_seconds: must be positive")
    max_age = _finite_number(cache_max_age_hours, "cache_max_age_hours", 0, FORECAST_DAYS * 24)
    _thresholds(rain_threshold_mm, heat_threshold_c, wind_threshold_kmh)
    if not isinstance(save_snapshot, bool) or (save_snapshot and snapshot_path is None):
        raise ValueError("save_snapshot must be boolean and needs a snapshot_path when enabled")
    if snapshot_path is not None and not isinstance(snapshot_path, (str, Path)):
        raise ValueError("snapshot_path: must be a path or None")
    path = Path(snapshot_path) if snapshot_path is not None else None
    settings = {"rain_threshold_mm": rain_threshold_mm, "heat_threshold_c": heat_threshold_c,
                "wind_threshold_kmh": wind_threshold_kmh}
    request_url = build_weather_url(latitude, longitude)
    errors = []
    try:
        payload = _fetch_weather(request_url, timeout)
        result = normalize_weather_response(payload, latitude, longitude, _timestamp(_utc_now()), **settings)
        if result["summary"]["status"] == "unavailable":
            raise WeatherDataError("Provider returned no usable weather variables")
    except HTTPError as exc:
        errors.append({"type": "http_error", "message": f"Open-Meteo returned HTTP {exc.code}"})
    except (TimeoutError, socket.timeout):
        errors.append({"type": "timeout", "message": "Open-Meteo request timed out"})
    except URLError as exc:
        kind = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "network_error"
        errors.append({"type": kind, "message": f"Open-Meteo request failed: {exc.reason}"})
    except WeatherDataError as exc:
        errors.append({"type": "invalid_response", "message": str(exc)})
    except OSError as exc:
        errors.append({"type": "network_error", "message": f"Open-Meteo request failed: {exc}"})
    else:
        if save_snapshot:
            try:
                _save_snapshot(path, payload, result, request_url)
            except (OSError, ValueError) as exc:
                result["warnings"].append(f"Snapshot was not saved: {exc}")
        return result
    if path is not None:
        try:
            cached = _load_snapshot(path, latitude, longitude, _utc_now(), max_age, settings)
            cached["errors"] = errors
            return cached
        except WeatherDataError as exc:
            errors.append({"type": "cache_unusable", "message": str(exc)})
    return _unavailable(latitude, longitude, errors, settings)
