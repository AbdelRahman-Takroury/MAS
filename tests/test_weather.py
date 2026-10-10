"""Synthetic provider fixtures for mocked tests; never production snapshots.

All network access is blocked by the autouse fixture. The checked-in genuine
snapshot is tested separately with its original timestamp, without live HTTP.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.services import weather


NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
STAMP = "2026-10-09T12:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self.body


@pytest.fixture(autouse=True)
def prohibit_live_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unit tests must not make live weather requests")
    monkeypatch.setattr(weather, "urlopen", forbidden)
    monkeypatch.setattr(weather, "_utc_now", lambda: NOW)


@pytest.fixture
def synthetic_payload():
    """Simulated API format only: these are fabricated test values, not forecasts."""
    dates = [(NOW.date() + timedelta(days=i)).isoformat() for i in range(7)]
    return {
        "latitude": 32.17, "longitude": 35.59, "timezone": "Asia/Amman",
        "utc_offset_seconds": 10800,
        "daily_units": {"time": "iso8601", **{key: spec[1] for key, spec in weather.DAILY_FIELDS.items()}},
        "daily": {
            "time": dates, "temperature_2m_max": [36, 35, 34, 40, 30, 32, 33],
            "temperature_2m_min": [20] * 7, "precipitation_sum": [6, 5, 0, 1, 0, 2, 0],
            "precipitation_probability_max": [90, 80, 0, 10, 0, 40, 0],
            "wind_speed_10m_max": [31, 30, 20, 40, 10, 20, 10],
            "et0_fao_evapotranspiration": [5] * 7, "weather_code": [61, 61, 0, 3, 0, 1, 2],
        },
        "hourly_units": {"time": "iso8601", "relative_humidity_2m": "%"},
        "hourly": {
            "time": [f"{day}T{hour:02d}:00" for day in dates for hour in range(24)],
            "relative_humidity_2m": [40 + i for i in range(7) for _ in range(24)],
        },
    }


def stub_http(monkeypatch, payload, status=200):
    calls = []
    def request(req, timeout):
        calls.append((req, timeout))
        return FakeResponse(payload, status)
    monkeypatch.setattr(weather, "urlopen", request)
    return calls


def fail_http(monkeypatch, exception=None):
    def request(*args, **kwargs):
        raise exception if exception is not None else URLError("offline test")
    monkeypatch.setattr(weather, "urlopen", request)


def normalize(payload, **kwargs):
    return weather.normalize_weather_response(payload, 32.19, 35.62, STAMP, **kwargs)


def snapshot(tmp_path, payload, **overrides):
    """Mock a previously retrieved snapshot contract solely for unit testing."""
    saved = {"snapshot_version": 1, "source": "open-meteo", "data_type": "forecast",
             "retrieved_at": STAMP, "latitude": 32.19, "longitude": 35.62,
             "request_url": weather.build_weather_url(32.19, 35.62),
             "api_response": payload, **overrides}
    path = tmp_path / "synthetic_snapshot_for_tests.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    return path


def test_valid_seven_day_forecast_and_normalization(synthetic_payload, monkeypatch):
    calls = stub_http(monkeypatch, synthetic_payload)
    result = weather.get_weather(32.19, 35.62, snapshot_path=None)
    assert len(calls) == 1
    assert result["status"] == "live"
    assert result["data_type"] == "forecast"
    assert result["retrieved_at"] == STAMP
    assert result["latitude"] == 32.19
    assert result["provider_latitude"] == 32.17
    assert len(result["daily"]) == 7
    first = result["daily"][0]
    assert first == {
        "date": "2026-10-09", "temperature_max_c": 36.0, "temperature_min_c": 20.0,
        "precipitation_mm": 6.0, "rain_probability_max_percent": 90.0,
        "wind_speed_max_kmh": 31.0, "et0_mm": 5.0, "weather_code": 61,
        "relative_humidity_mean_percent": 40.0, "relative_humidity_hours_available": 24,
        "relative_humidity_hours_expected": 24,
    }
    assert result["errors"] == []
    assert result["summary"]["status"] == "complete"


def test_correct_official_request_url_parameters(synthetic_payload, monkeypatch):
    calls = stub_http(monkeypatch, synthetic_payload)
    weather.get_weather(32.19, 35.62, timeout_seconds=7, snapshot_path=None)
    req, timeout = calls[0]
    url = urlsplit(req.full_url)
    assert url.scheme == "https"
    assert url.netloc == "api.open-meteo.com"
    assert url.path == "/v1/forecast"
    params = parse_qs(url.query)
    assert params == {
        "latitude": ["32.19"], "longitude": ["35.62"],
        "daily": [",".join(weather.DAILY_FIELDS)], "hourly": ["relative_humidity_2m"],
        "timezone": ["Asia/Amman"], "forecast_days": ["7"],
        "temperature_unit": ["celsius"], "wind_speed_unit": ["kmh"],
        "precipitation_unit": ["mm"], "timeformat": ["iso8601"],
    }
    assert timeout == 7


@pytest.mark.parametrize("lat,lon", [(91, 35), (-91, 35), (32, 181), (32, -181),
                                         (None, 35), ("32", 35), (True, 35), (32, False),
                                         (float("nan"), 35), (32, float("inf")), (10 ** 1000, 35)])
def test_invalid_coordinates_fail_before_http(lat, lon):
    with pytest.raises(ValueError):
        weather.get_weather(lat, lon)


@pytest.mark.parametrize("lat,lon", [(-90, -180), (90, 180), (0, 0)])
def test_coordinate_boundaries(lat, lon):
    assert weather.build_weather_url(lat, lon).startswith(weather.API_URL)


def test_local_date_humidity_aggregation_partial_coverage(synthetic_payload):
    synthetic_payload["hourly"]["relative_humidity_2m"][0] = 10
    synthetic_payload["hourly"]["relative_humidity_2m"][1] = 30
    synthetic_payload["hourly"]["relative_humidity_2m"][2:24] = [None] * 22
    result = normalize(synthetic_payload)
    assert result["daily"][0]["relative_humidity_mean_percent"] == 20
    assert result["daily"][0]["relative_humidity_hours_available"] == 2
    assert result["daily"][1]["relative_humidity_mean_percent"] == 41
    assert result["summary"]["status"] == "partial"
    assert any("2/24" in warning for warning in result["warnings"])


@pytest.mark.parametrize("key", ["hourly", "hourly_units"])
def test_missing_humidity_remains_null(synthetic_payload, key):
    del synthetic_payload[key]
    result = normalize(synthetic_payload)
    assert all(day["relative_humidity_mean_percent"] is None for day in result["daily"])
    assert result["summary"]["humidity_hours_available"] == 0
    assert result["summary"]["status"] == "partial"
    assert result["warnings"]


def test_missing_and_null_et0_are_not_zero(synthetic_payload):
    synthetic_payload["daily"]["et0_fao_evapotranspiration"][0] = None
    result = normalize(synthetic_payload)
    assert result["daily"][0]["et0_mm"] is None
    assert result["summary"]["total_et0_mm"] == 30
    assert result["summary"]["metric_status"]["total_et0_mm"] == "partial"
    del synthetic_payload["daily"]["et0_fao_evapotranspiration"]
    result = normalize(synthetic_payload)
    assert result["summary"]["total_et0_mm"] is None
    assert result["summary"]["metric_status"]["total_et0_mm"] == "unavailable"


def test_null_precipitation_preserves_probability_without_inventing_rain(synthetic_payload):
    synthetic_payload["daily"]["precipitation_sum"][0] = None
    result = normalize(synthetic_payload)
    assert result["daily"][0]["precipitation_mm"] is None
    assert result["daily"][0]["rain_probability_max_percent"] == 90
    assert result["summary"]["total_precipitation_mm"] == 8
    assert result["summary"]["metric_status"]["total_precipitation_mm"] == "partial"
    assert not any(a["date"] == "2026-10-09" and a["type"] == "rain_irrigation_review" for a in result["advisories"])


def test_short_and_long_arrays_are_reported(synthetic_payload):
    synthetic_payload["daily"]["temperature_2m_max"] = [36] * 2
    synthetic_payload["daily"]["precipitation_sum"].append(99)
    result = normalize(synthetic_payload)
    assert result["daily"][2]["temperature_max_c"] is None
    assert result["summary"]["available_days_per_metric"]["heat_days"] == 2
    assert result["summary"]["metric_status"]["heat_days"] == "partial"
    assert result["summary"]["total_precipitation_mm"] == 14
    assert any("array length" in warning for warning in result["warnings"])


def test_partial_forecast_dates_not_fabricated(synthetic_payload):
    synthetic_payload["daily"] = {key: values[:3] for key, values in synthetic_payload["daily"].items()}
    result = normalize(synthetic_payload)
    assert len(result["daily"]) == 3
    assert result["summary"]["available_days"] == 3
    assert result["summary"]["requested_days"] == 7
    assert result["summary"]["metric_status"]["total_precipitation_mm"] == "partial"


@pytest.mark.parametrize("field", list(weather.DAILY_FIELDS))
def test_missing_daily_field_is_explicit(synthetic_payload, field):
    del synthetic_payload["daily"][field]
    result = normalize(synthetic_payload)
    key = weather.DAILY_FIELDS[field][0]
    assert all(day[key] is None for day in result["daily"])
    assert result["summary"]["available_days_per_field"][key] == 0


@pytest.mark.parametrize("field", list(weather.DAILY_FIELDS))
@pytest.mark.parametrize("value", ["bad", True, float("nan"), float("inf")])
def test_invalid_daily_numbers_become_unavailable(synthetic_payload, field, value):
    synthetic_payload["daily"][field][0] = value
    result = normalize(synthetic_payload)
    assert result["daily"][0][weather.DAILY_FIELDS[field][0]] is None
    assert result["summary"]["status"] == "partial"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value", [("precipitation_sum", -1), ("wind_speed_10m_max", -1),
                                             ("et0_fao_evapotranspiration", -1),
                                             ("precipitation_probability_max", 101),
                                             ("precipitation_probability_max", -1), ("weather_code", 1.5)])
def test_invalid_ranges(synthetic_payload, field, value):
    synthetic_payload["daily"][field][0] = value
    assert normalize(synthetic_payload)["daily"][0][weather.DAILY_FIELDS[field][0]] is None


def test_negative_temperature_is_valid_but_inverted_extrema_are_not(synthetic_payload):
    synthetic_payload["daily"]["temperature_2m_max"][0] = -1
    synthetic_payload["daily"]["temperature_2m_min"][0] = -10
    assert normalize(synthetic_payload)["daily"][0]["temperature_max_c"] == -1
    synthetic_payload["daily"]["temperature_2m_min"][0] = 5
    first = normalize(synthetic_payload)["daily"][0]
    assert first["temperature_max_c"] is first["temperature_min_c"] is None


def test_unknown_wmo_code_is_preserved_without_invented_label(synthetic_payload):
    synthetic_payload["daily"]["weather_code"][0] = 4
    result = normalize(synthetic_payload)
    assert result["daily"][0]["weather_code"] == 4
    assert "weather_label" not in result["daily"][0]
    assert any("unknown WMO" in warning for warning in result["warnings"])


@pytest.mark.parametrize("field", list(weather.DAILY_FIELDS))
def test_unexpected_daily_units_reject_response(synthetic_payload, field):
    synthetic_payload["daily_units"][field] = "wrong"
    with pytest.raises(weather.WeatherDataError, match="Unexpected units"):
        normalize(synthetic_payload)


def test_missing_unit_does_not_assume_original_unit(synthetic_payload):
    del synthetic_payload["daily_units"]["precipitation_sum"]
    result = normalize(synthetic_payload)
    assert result["daily"][0]["precipitation_mm"] is None
    assert any("units missing" in warning for warning in result["warnings"])


@pytest.mark.parametrize("key,value", [("timezone", "UTC"), ("utc_offset_seconds", 0),
                                           ("daily", None), ("daily_units", None)])
def test_critical_metadata_rejects_response(synthetic_payload, key, value):
    synthetic_payload[key] = value
    with pytest.raises(weather.WeatherDataError):
        normalize(synthetic_payload)


@pytest.mark.parametrize("value", [[], None, "bad"])
def test_invalid_daily_time_array(synthetic_payload, value):
    synthetic_payload["daily"]["time"] = value
    with pytest.raises(weather.WeatherDataError):
        normalize(synthetic_payload)


def test_invalid_and_duplicate_dates_are_excluded(synthetic_payload):
    synthetic_payload["daily"]["time"][0] = "2026-02-30"
    synthetic_payload["daily"]["time"][1] = synthetic_payload["daily"]["time"][2]
    result = normalize(synthetic_payload)
    assert len(result["daily"]) == 5
    assert len({day["date"] for day in result["daily"]}) == 5
    assert any("invalid date" in warning for warning in result["warnings"])
    assert any("duplicate daily" in warning for warning in result["warnings"])


def test_missing_daily_date_is_partial_even_if_arrays_have_seven_values(synthetic_payload):
    synthetic_payload["daily"]["time"][0] = "2026-10-08"
    result = normalize(synthetic_payload)
    assert len(result["daily"]) == 6
    assert all(day["date"] >= "2026-10-09" for day in result["daily"])


def test_humidity_invalid_dates_duplicates_ranges_and_lengths(synthetic_payload):
    synthetic_payload["hourly"]["time"][0] = "not-a-time"
    synthetic_payload["hourly"]["time"][1] = synthetic_payload["hourly"]["time"][2]
    synthetic_payload["hourly"]["relative_humidity_2m"][3] = 101
    synthetic_payload["hourly"]["relative_humidity_2m"].pop()
    result = normalize(synthetic_payload)
    assert result["daily"][0]["relative_humidity_hours_available"] == 21
    assert result["daily"][-1]["relative_humidity_hours_available"] == 23
    assert result["daily"][0]["relative_humidity_mean_percent"] == 40


def test_humidity_unexpected_unit_does_not_create_a_mean(synthetic_payload):
    synthetic_payload["hourly_units"]["relative_humidity_2m"] = "fraction"
    assert normalize(synthetic_payload)["daily"][0]["relative_humidity_mean_percent"] is None


@pytest.mark.parametrize("exception,error_type", [
    (HTTPError(weather.API_URL, 503, "unavailable", None, None), "http_error"),
    (TimeoutError("timeout"), "timeout"), (URLError(TimeoutError("timeout")), "timeout"),
    (URLError("network unavailable"), "network_error"), (OSError("connection failed"), "network_error"),
])
def test_http_and_timeout_failures_return_unavailable(monkeypatch, exception, error_type):
    fail_http(monkeypatch, exception)
    result = weather.get_weather(32.19, 35.62, snapshot_path=None)
    assert result["status"] == "unavailable"
    assert result["retrieved_at"] is None
    assert result["daily"] == result["advisories"] == []
    assert result["errors"][0]["type"] == error_type
    assert result["summary"]["total_et0_mm"] is None


@pytest.mark.parametrize("payload", [b"bad JSON", b"\xff", [], {"error": True}, {}])
def test_bad_api_responses_return_structured_errors(monkeypatch, payload):
    stub_http(monkeypatch, payload)
    result = weather.get_weather(32.19, 35.62, snapshot_path=None)
    assert result["status"] == "unavailable"
    assert result["errors"][0]["type"] == "invalid_response"


def test_non_200_status_without_http_exception(monkeypatch):
    stub_http(monkeypatch, {}, status=429)
    assert weather.get_weather(32.19, 35.62, snapshot_path=None)["status"] == "unavailable"


def test_valid_cache_used_only_after_live_failure(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload)
    fail_http(monkeypatch)
    result = weather.get_weather(32.19, 35.62, snapshot_path=path)
    assert result["status"] == "cached"
    assert result["retrieved_at"] == STAMP
    assert result["data_type"] == "forecast"
    assert result["summary"]["status"] == "complete"
    assert result["errors"][0]["type"] == "network_error"
    assert any("Cached forecast" in warning for warning in result["warnings"])


def test_live_wins_over_saved_snapshot(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload, retrieved_at="2020-01-01T00:00:00Z")
    stub_http(monkeypatch, synthetic_payload)
    assert weather.get_weather(32.19, 35.62, snapshot_path=path)["status"] == "live"


@pytest.mark.parametrize("overrides", [
    {"latitude": 32.2}, {"longitude": 36}, {"latitude": True},
    {"retrieved_at": "2026-10-07T12:00:00Z"}, {"retrieved_at": "2026-10-10T12:00:00Z"},
    {"retrieved_at": "bad"}, {"retrieved_at": "2026-10-09T12:00:00"},
    {"source": "synthetic"}, {"data_type": "synthetic_demo"}, {"snapshot_version": 99},
])
def test_unusable_snapshots_are_not_current_forecasts(tmp_path, synthetic_payload, monkeypatch, overrides):
    fail_http(monkeypatch)
    path = snapshot(tmp_path, synthetic_payload, **overrides)
    result = weather.get_weather(32.19, 35.62, snapshot_path=path)
    assert result["status"] == "unavailable"
    assert result["daily"] == []
    assert result["errors"][-1]["type"] == "cache_unusable"


def test_cache_discards_past_dates_and_marks_remaining_period_partial(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload)
    fail_http(monkeypatch)
    monkeypatch.setattr(weather, "_utc_now", lambda: NOW + timedelta(hours=12))
    result = weather.get_weather(32.19, 35.62, snapshot_path=path)
    assert result["status"] == "cached"
    assert len(result["daily"]) == 6
    assert result["daily"][0]["date"] == "2026-10-10"
    assert result["retrieved_at"] == STAMP
    assert result["summary"]["metric_status"]["total_et0_mm"] == "partial"


def test_expired_forecast_is_not_presented_as_current(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload)
    fail_http(monkeypatch)
    monkeypatch.setattr(weather, "_utc_now", lambda: NOW + timedelta(days=7))
    result = weather.get_weather(32.19, 35.62, snapshot_path=path, cache_max_age_hours=168)
    assert result["status"] == "unavailable"
    assert result["daily"] == []


def test_cache_dates_must_match_original_retrieval_period(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload, retrieved_at="2026-10-08T12:00:00Z")
    fail_http(monkeypatch)
    result = weather.get_weather(32.19, 35.62, snapshot_path=path, cache_max_age_hours=48)
    assert result["status"] == "unavailable"
    assert "original retrieval period" in result["errors"][-1]["message"]


@pytest.mark.parametrize("content", ["{bad", "null", "[]"])
def test_malformed_cache(tmp_path, monkeypatch, content):
    path = tmp_path / "bad_cache.json"
    path.write_text(content, encoding="utf-8")
    fail_http(monkeypatch)
    assert weather.get_weather(32.19, 35.62, snapshot_path=path)["status"] == "unavailable"


def test_missing_cache_is_unavailable(tmp_path, monkeypatch):
    fail_http(monkeypatch)
    result = weather.get_weather(32.19, 35.62, snapshot_path=tmp_path / "missing.json")
    assert result["status"] == "unavailable"
    assert len(result["errors"]) == 2


def test_advisories_have_values_dates_thresholds_and_no_irrigation_prescription(synthetic_payload):
    result = normalize(synthetic_payload)
    first = [a for a in result["advisories"] if a["date"] == "2026-10-09"]
    assert {a["type"] for a in first} == {"rain_irrigation_review", "heat_inspection", "wind_inspection"}
    rain = next(a for a in first if a["type"] == "rain_irrigation_review")
    assert rain["value"] == 6
    assert rain["threshold"] == 5
    assert "soil moisture" in rain["message"]
    assert not any(a["date"] == "2026-10-10" for a in result["advisories"])
    assert all(set(a) == {"date", "type", "metric", "value", "threshold", "message"} for a in first)


def test_independent_advisory_helper_missing_values():
    day = {"date": "2026-10-09", "precipitation_mm": None, "temperature_max_c": None, "wind_speed_max_kmh": None}
    assert weather.generate_weather_advisories([day]) == []


def test_configurable_thresholds_apply_to_summary_and_advisories(synthetic_payload):
    result = normalize(synthetic_payload, rain_threshold_mm=1, heat_threshold_c=30, wind_threshold_kmh=15)
    assert result["summary"]["heat_days"] == 6
    assert result["summary"]["wind_days"] == 5
    assert sum(a["type"] == "rain_irrigation_review" for a in result["advisories"]) == 3
    assert result["summary"]["thresholds"]["rain_mm"] == 1


def test_complete_summary_actual_expected_values(synthetic_payload):
    summary = normalize(synthetic_payload)["summary"]
    assert summary["total_precipitation_mm"] == 14
    assert summary["total_et0_mm"] == 35
    assert summary["heat_days"] == 2
    assert summary["wind_days"] == 2
    assert summary["rainy_days"] == 4
    assert summary["available_days"] == 7
    assert summary["humidity_hours_available"] == summary["humidity_hours_expected"] == 168
    assert set(summary["metric_status"].values()) == {"complete"}


def test_empty_summary_does_not_fabricate_zero_totals():
    result = weather.summarize_weather([])
    assert result["status"] == "unavailable"
    assert result["total_precipitation_mm"] is result["total_et0_mm"] is None
    assert result["heat_days"] is result["wind_days"] is result["rainy_days"] is None


def test_live_complete_snapshot_saved_atomically(tmp_path, synthetic_payload, monkeypatch):
    path = tmp_path / "saved_mock_response.json"
    stub_http(monkeypatch, synthetic_payload)
    result = weather.get_weather(32.19, 35.62, snapshot_path=path, save_snapshot=True)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["retrieved_at"] == result["retrieved_at"]
    assert saved["api_response"] == synthetic_payload
    assert saved["latitude"] == 32.19
    assert saved["data_type"] == "forecast"
    assert not list(tmp_path.glob("*.tmp"))


def test_partial_or_malformed_live_response_does_not_overwrite_valid_cache(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload)
    before = path.read_bytes()
    partial = deepcopy(synthetic_payload)
    partial["daily"]["et0_fao_evapotranspiration"][0] = None
    stub_http(monkeypatch, partial)
    result = weather.get_weather(32.19, 35.62, snapshot_path=path, save_snapshot=True)
    assert result["status"] == "live"
    assert path.read_bytes() == before
    assert any("not saved" in warning for warning in result["warnings"])
    stub_http(monkeypatch, {})
    assert weather.get_weather(32.19, 35.62, snapshot_path=path, save_snapshot=True)["status"] == "cached"
    assert path.read_bytes() == before


def test_saving_is_opt_in(tmp_path, synthetic_payload, monkeypatch):
    path = tmp_path / "should_not_exist.json"
    stub_http(monkeypatch, synthetic_payload)
    weather.get_weather(32.19, 35.62, snapshot_path=path)
    assert not path.exists()


def test_inconsistent_extra_array_values_do_not_replace_valid_snapshot(tmp_path, synthetic_payload, monkeypatch):
    path = snapshot(tmp_path, synthetic_payload)
    before = path.read_bytes()
    synthetic_payload["daily"]["precipitation_sum"].append(99)
    stub_http(monkeypatch, synthetic_payload)
    result = weather.get_weather(32.19, 35.62, snapshot_path=path, save_snapshot=True)
    assert result["status"] == "live"
    assert result["summary"]["status"] == "complete"
    assert path.read_bytes() == before
    assert any("Inconsistent raw arrays" in warning for warning in result["warnings"])


def test_snapshot_write_failure_does_not_hide_live_data(tmp_path, synthetic_payload, monkeypatch):
    stub_http(monkeypatch, synthetic_payload)
    def cannot_save(*args):
        raise OSError("test read-only cache directory")
    monkeypatch.setattr(weather, "_save_snapshot", cannot_save)
    result = weather.get_weather(32.19, 35.62, snapshot_path=tmp_path / "not_saved.json", save_snapshot=True)
    assert result["status"] == "live"
    assert result["summary"]["total_et0_mm"] == 35
    assert any("not saved" in warning for warning in result["warnings"])


@pytest.mark.parametrize("settings", [
    {"timeout_seconds": 0}, {"timeout_seconds": 61}, {"timeout_seconds": float("nan")},
    {"cache_max_age_hours": -1}, {"cache_max_age_hours": 169},
    {"rain_threshold_mm": -1}, {"wind_threshold_kmh": -1}, {"heat_threshold_c": float("inf")},
    {"snapshot_path": 1}, {"save_snapshot": 1}, {"save_snapshot": True, "snapshot_path": None},
])
def test_bad_options_fail_before_network(settings):
    with pytest.raises(ValueError):
        weather.get_weather(32.19, 35.62, **settings)


def test_unavailable_response_preserves_custom_thresholds(monkeypatch):
    fail_http(monkeypatch)
    result = weather.get_weather(32.19, 35.62, snapshot_path=None, heat_threshold_c=40)
    assert result["summary"]["thresholds"]["heat_c"] == 40


def test_json_serialization_and_no_payload_mutation(synthetic_payload):
    original = deepcopy(synthetic_payload)
    result = normalize(synthetic_payload)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert synthetic_payload == original


def test_non_forecast_or_labelled_synthetic_provider_data_is_rejected(synthetic_payload, monkeypatch):
    synthetic_payload["data_type"] = "synthetic_demo"
    stub_http(monkeypatch, synthetic_payload)
    assert weather.get_weather(32.19, 35.62, snapshot_path=None)["status"] == "unavailable"


def test_all_variables_missing_is_unavailable(synthetic_payload, monkeypatch):
    synthetic_payload["daily"] = {"time": synthetic_payload["daily"]["time"]}
    del synthetic_payload["hourly"]
    stub_http(monkeypatch, synthetic_payload)
    assert weather.get_weather(32.19, 35.62, snapshot_path=None)["status"] == "unavailable"


def test_overflowing_weather_aggregate_is_not_json_infinity(synthetic_payload):
    synthetic_payload["daily"]["precipitation_sum"] = [1e308] * 7
    result = normalize(synthetic_payload)
    assert result["summary"]["total_precipitation_mm"] is None
    assert result["summary"]["metric_status"]["total_precipitation_mm"] == "unavailable"
    json.dumps(result, allow_nan=False)


def test_genuine_smoke_snapshot_and_documented_example_agree():
    saved = json.loads((ROOT / "data/sample_weather.json").read_text(encoding="utf-8"))
    example = json.loads((ROOT / "docs/member3/weather_example.json").read_text(encoding="utf-8"))
    assert saved["source"] == "open-meteo"
    assert saved["data_type"] == "forecast"
    normalized = weather.normalize_weather_response(saved["api_response"], saved["latitude"], saved["longitude"], saved["retrieved_at"])
    assert normalized == example
    assert len(example["daily"]) == 7
    assert example["summary"]["humidity_hours_available"] == 168


def test_genuine_snapshot_is_usable_only_when_its_timestamp_is_fresh(monkeypatch):
    saved = json.loads((ROOT / "data/sample_weather.json").read_text(encoding="utf-8"))
    retrieved = datetime.fromisoformat(saved["retrieved_at"].replace("Z", "+00:00"))
    monkeypatch.setattr(weather, "_utc_now", lambda: retrieved)
    fail_http(monkeypatch)
    result = weather.get_weather(saved["latitude"], saved["longitude"], snapshot_path=ROOT / "data/sample_weather.json")
    assert result["status"] == "cached"
    assert result["retrieved_at"] == saved["retrieved_at"]
    monkeypatch.setattr(weather, "_utc_now", lambda: retrieved + timedelta(days=8))
    assert weather.get_weather(saved["latitude"], saved["longitude"], snapshot_path=ROOT / "data/sample_weather.json")["status"] == "unavailable"
