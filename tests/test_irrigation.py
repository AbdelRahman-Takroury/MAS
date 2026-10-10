"""Synthetic normalized Weather Engine contract fixtures; no real HTTP calls."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import localcontext, ROUND_DOWN
import json
from pathlib import Path

import pytest

from backend.engines.irrigation import calculate_irrigation, summarize_irrigation_records


NOW = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def farm():
    return {"crop": "tomato", "area_m2": 1000, "crop_stage": "mid_season", "irrigation_method": "drip",
            "irrigation_efficiency": 0.9, "effective_rain_fraction": 0.8, "system_flow_liters_per_hour": 2000}


@pytest.fixture
def forecast():
    """Constructed contract mock; these values are not official weather records."""
    return {
        "status": "live", "source": "open-meteo", "data_type": "forecast", "timezone": "Asia/Amman",
        "retrieved_at": "2026-10-10T09:00:00Z", "forecast_start_date": "2026-10-10",
        "forecast_end_date": "2026-10-16", "summary": {"requested_days": 7, "status": "complete"},
        "units": {"et0": "mm/day", "precipitation": "mm"}, "warnings": [],
        "daily": [{"date": (NOW.date() + timedelta(days=i)).isoformat(), "et0_mm": 5, "precipitation_mm": 0} for i in range(7)],
    }


def calculate(farm, forecast, **kwargs):
    return calculate_irrigation(farm, forecast, reference_time=NOW, **kwargs)


def test_independent_mathematical_example(farm, forecast):
    result = calculate(farm, forecast)
    first = result["daily"][0]
    assert first["etc_mm"] == 5.75
    assert first["crop_water_consumption_liters"] == 5750
    assert first["effective_rain_mm"] == 0
    assert first["net_irrigation_mm"] == 5.75
    assert first["net_irrigation_liters"] == 5750
    assert first["gross_irrigation_liters"] == pytest.approx(6388.888888888889)
    assert first["runtime_hours"] == pytest.approx(3.1944444444444446)
    assert first["status"] == "calculated"
    assert result["summary"]["total_etc_mm"] == 40.25
    assert result["summary"]["total_net_irrigation_liters"] == 40250
    assert result["summary"]["total_gross_irrigation_liters"] == pytest.approx(44722.22222222222)
    assert result["summary"]["complete_days"] == 7
    assert result["summary"]["incomplete_days"] == 0


@pytest.mark.parametrize("stage,kc,etc", [("initial", 0.6, 3), ("development", 0.875, 4.375),
                                             ("mid_season", 1.15, 5.75), ("late_season", 0.8, 4)])
def test_crop_stages(farm, forecast, stage, kc, etc):
    farm["crop_stage"] = stage
    result = calculate(farm, forecast)
    assert result["kc"]["value"] == kc
    assert result["daily"][0]["etc_mm"] == etc
    if stage == "development":
        assert result["kc"]["source"] == "development_midpoint_approximation"
        assert any("not a universal FAO" in warning for warning in result["warnings"])
    if stage == "late_season":
        assert any("no continuous decline" in warning for warning in result["warnings"])


def test_override_and_configured_coefficients(farm, forecast):
    farm["kc_override"] = 1.2
    result = calculate(farm, forecast)
    assert result["daily"][0]["etc_mm"] == 6
    assert result["kc"]["source"] == "farmer_kc_override"
    assert result["kc"]["source_url"] is None
    del farm["kc_override"]
    farm["crop_stage"] = "development"
    result = calculate(farm, forecast, kc_parameters={"initial": 0.5, "mid_season": 1.1})
    assert result["kc"]["value"] == 0.8
    result = calculate(farm, forecast, kc_parameters={"development": 0.9})
    assert result["kc"]["source"] == "configured_stage_coefficient"
    assert result["daily"][0]["etc_mm"] == 4.5


def test_missing_stage_can_use_explicit_override(farm, forecast):
    del farm["crop_stage"]
    with pytest.raises(ValueError, match="crop_stage"):
        calculate(farm, forecast)
    farm["kc_override"] = 0.9
    assert calculate(farm, forecast)["kc"]["value"] == 0.9


@pytest.mark.parametrize("value", ["unknown", "flowering", "", [], 1, True])
def test_invalid_stage(farm, forecast, value):
    farm["crop_stage"] = value
    with pytest.raises(ValueError, match="crop_stage"):
        calculate(farm, forecast)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "1.15", True])
def test_invalid_kc_override(farm, forecast, value):
    farm["kc_override"] = value
    with pytest.raises(ValueError, match="kc_override"):
        calculate(farm, forecast)


@pytest.mark.parametrize("parameters", [[], {"wrong": 1}, {"initial": 0}, {"development": -1}])
def test_invalid_kc_configuration(farm, forecast, parameters):
    with pytest.raises(ValueError, match="kc_parameters"):
        calculate(farm, forecast, kc_parameters=parameters)


@pytest.mark.parametrize("field,value", [
    ("area_m2", 0), ("area_m2", -1), ("area_m2", float("nan")), ("area_m2", True),
    ("area_m2", "1000"), ("irrigation_efficiency", 0), ("irrigation_efficiency", -1),
    ("irrigation_efficiency", 1.1), ("effective_rain_fraction", -0.1), ("effective_rain_fraction", 1.1),
    ("system_flow_liters_per_hour", 0), ("system_flow_liters_per_hour", -1),
    ("system_flow_liters_per_hour", float("inf")),
])
def test_invalid_farm_numbers(farm, forecast, field, value):
    farm[field] = value
    with pytest.raises(ValueError, match=field):
        calculate(farm, forecast)


@pytest.mark.parametrize("field", ["crop", "area_m2", "irrigation_method"])
def test_missing_required_farm_fields(farm, forecast, field):
    del farm[field]
    with pytest.raises(ValueError, match=field):
        calculate(farm, forecast)


def test_unsupported_crop_method_and_request_types(farm, forecast):
    with pytest.raises(ValueError):
        calculate(None, forecast)
    with pytest.raises(ValueError):
        calculate(farm, None)
    farm["crop"] = "potato"
    with pytest.raises(ValueError, match="tomato"):
        calculate(farm, forecast)
    farm["crop"] = "tomato"
    farm["irrigation_method"] = "sprinkler"
    with pytest.raises(ValueError, match="drip"):
        calculate(farm, forecast)


def test_zero_et0_produces_zero_demand(farm, forecast):
    forecast["daily"][0]["et0_mm"] = 0
    first = calculate(farm, forecast)["daily"][0]
    for field in ("etc_mm", "crop_water_consumption_liters", "net_irrigation_liters", "gross_irrigation_liters", "runtime_hours"):
        assert first[field] == 0


@pytest.mark.parametrize("field", ["et0_mm", "precipitation_mm"])
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "5"])
def test_invalid_daily_weather_values_withhold_dependencies(farm, forecast, field, value):
    forecast["daily"][0][field] = value
    result = calculate(farm, forecast)
    assert result["status"] == "partial"
    assert result["daily"][0][field] is None
    assert result["daily"][0]["gross_irrigation_liters"] is None
    assert result["summary"]["total_gross_irrigation_liters"] is None
    assert result["daily"][0]["warnings"]


def test_zero_rain_needs_no_effectiveness_assumption(farm, forecast):
    del farm["effective_rain_fraction"]
    result = calculate(farm, forecast)
    assert result["status"] == "calculated"
    assert result["daily"][0]["effective_rain_mm"] == 0
    assert result["daily"][0]["net_irrigation_liters"] == 5750


def test_positive_rain_with_explicit_fraction(farm, forecast):
    forecast["daily"][0]["precipitation_mm"] = 2
    first = calculate(farm, forecast)["daily"][0]
    assert first["effective_rain_mm"] == 1.6
    assert first["net_irrigation_mm"] == 4.15
    assert first["net_irrigation_liters"] == 4150
    assert first["gross_irrigation_liters"] == pytest.approx(4611.111111111111)


def test_positive_rain_without_fraction_returns_crop_consumption_only(farm, forecast):
    del farm["effective_rain_fraction"]
    forecast["daily"][0]["precipitation_mm"] = 2
    first = calculate(farm, forecast)["daily"][0]
    assert first["etc_mm"] == 5.75
    assert first["crop_water_consumption_liters"] == 5750
    assert first["effective_rain_mm"] is first["net_irrigation_liters"] is first["gross_irrigation_liters"] is None


def test_excess_rain_not_transferred_between_dates(farm, forecast):
    forecast["daily"][0]["precipitation_mm"] = 100
    result = calculate(farm, forecast)
    assert result["daily"][0]["effective_rain_mm"] == 80
    assert result["daily"][0]["net_irrigation_liters"] == 0
    assert result["daily"][1]["net_irrigation_liters"] == 5750
    assert result["summary"]["total_net_irrigation_liters"] == 34500


@pytest.mark.parametrize("fraction,effective,net", [(0, 0, 5750), (1, 2, 3750)])
def test_rain_fraction_boundaries(farm, forecast, fraction, effective, net):
    farm["effective_rain_fraction"] = fraction
    forecast["daily"][0]["precipitation_mm"] = 2
    first = calculate(farm, forecast)["daily"][0]
    assert first["effective_rain_mm"] == effective
    assert first["net_irrigation_liters"] == net


def test_missing_efficiency_net_known_gross_and_runtime_unavailable(farm, forecast):
    del farm["irrigation_efficiency"]
    result = calculate(farm, forecast)
    assert result["status"] == "partial"
    assert result["daily"][0]["net_irrigation_liters"] == 5750
    assert result["daily"][0]["gross_irrigation_liters"] is None
    assert result["daily"][0]["runtime_hours"] is None
    assert result["summary"]["total_net_irrigation_liters"] == 40250
    assert result["summary"]["total_gross_irrigation_liters"] is None


def test_missing_flow_does_not_make_water_demand_incomplete(farm, forecast):
    del farm["system_flow_liters_per_hour"]
    result = calculate(farm, forecast)
    assert result["status"] == "calculated"
    assert result["daily"][0]["runtime_hours"] is None
    assert result["summary"]["total_runtime_hours"] is None


@pytest.mark.parametrize("field", ["et0_mm", "precipitation_mm"])
def test_missing_weather_fields_and_explicit_partial_totals(farm, forecast, field):
    del forecast["daily"][0][field]
    result = calculate(farm, forecast)
    assert result["summary"]["total_gross_irrigation_liters"] is None
    partial = result["summary"]["partial_totals"]["total_gross_irrigation_liters"]
    assert partial["covered_days"] == 6
    assert partial["requested_days"] == 7
    assert partial["value"] == pytest.approx(38333.333333333336)
    assert partial["status"] == "partial"
    assert "2026-10-10" not in partial["dates"]


def test_missing_all_et0_is_unavailable(farm, forecast):
    for day in forecast["daily"]:
        day["et0_mm"] = None
    result = calculate(farm, forecast)
    assert result["status"] == "unavailable"
    assert result["summary"]["total_crop_water_consumption_liters"] is None


def test_missing_date_and_duplicate_date_prevent_full_period_total(farm, forecast):
    forecast["daily"][0]["date"] = forecast["daily"][1]["date"]
    result = calculate(farm, forecast)
    assert result["status"] == "partial"
    assert result["summary"]["available_days"] == 6
    assert result["summary"]["incomplete_days"] == 1
    assert result["summary"]["total_etc_mm"] is None


def test_partial_weather_missing_humidity_does_not_block_valid_water_inputs(farm, forecast):
    forecast["summary"]["status"] = "partial"
    forecast["warnings"] = ["humidity unavailable"]
    result = calculate(farm, forecast)
    assert result["status"] == "calculated"
    assert "humidity unavailable" in result["warnings"]


def test_cached_weather_preserves_provenance(farm, forecast):
    forecast["status"] = "cached"
    result = calculate(farm, forecast)
    assert result["status"] == "calculated"
    assert result["weather_provenance"]["status"] == "cached"
    assert result["weather_provenance"]["retrieved_at"] == forecast["retrieved_at"]


@pytest.mark.parametrize("field,value", [
    ("status", "unavailable"), ("status", "synthetic_demo"), ("source", "other-provider"),
    ("data_type", "observation"), ("data_type", "synthetic"), ("timezone", "UTC"),
    ("retrieved_at", "2026-10-08T09:00:00Z"), ("retrieved_at", "2026-10-11T09:00:00Z"),
    ("retrieved_at", "bad"), ("retrieved_at", "2026-10-10T09:00:00"),
    ("forecast_start_date", "bad"), ("daily", None), ("synthetic", True),
])
def test_invalid_expired_or_synthetic_weather_unavailable(farm, forecast, field, value):
    forecast[field] = value
    result = calculate(farm, forecast)
    assert result["status"] == "unavailable"
    assert result["daily"] == []
    assert result["summary"]["total_gross_irrigation_liters"] is None
    assert result["warnings"]


def test_unexpected_units_rejected(farm, forecast):
    forecast["units"]["et0"] = "liters/day"
    assert calculate(farm, forecast)["status"] == "unavailable"
    forecast["units"] = {"et0": "mm/day", "precipitation": "%"}
    assert calculate(farm, forecast)["status"] == "unavailable"


def test_expired_forecast_dates_never_become_future_demand(farm, forecast):
    forecast["forecast_start_date"] = "2026-10-01"
    forecast["forecast_end_date"] = "2026-10-07"
    assert calculate(farm, forecast)["status"] == "unavailable"


def test_weather_period_metadata_must_agree(farm, forecast):
    forecast["summary"]["requested_days"] = 6
    assert calculate(farm, forecast)["status"] == "unavailable"


def test_single_day_explicit_period(farm, forecast):
    forecast["summary"]["requested_days"] = 1
    forecast["forecast_end_date"] = forecast["forecast_start_date"]
    forecast["daily"] = forecast["daily"][:1]
    result = calculate(farm, forecast)
    assert result["status"] == "calculated"
    assert result["period_days"] == 1
    assert result["summary"]["total_gross_irrigation_liters"] == pytest.approx(6388.888888888889)


def test_actual_genuine_weather_replay_and_current_date_filtering(farm):
    root = Path(__file__).resolve().parents[1]
    actual = json.loads((root / "docs/member3/weather_example.json").read_text(encoding="utf-8"))
    reference = datetime.fromisoformat(actual["retrieved_at"].replace("Z", "+00:00"))
    replay = calculate_irrigation(farm, actual, reference_time=reference)
    assert replay["status"] == "calculated"
    assert replay["summary"]["total_crop_water_consumption_liters"] == 34362
    assert replay["summary"]["total_gross_irrigation_liters"] == 38180
    actual["status"] = "cached"
    current = calculate(farm, actual)
    assert current["status"] == "partial"
    assert current["period_start_date"] == "2026-10-10"
    assert current["period_end_date"] == "2026-10-16"
    assert len(current["daily"]) == 6
    assert current["summary"]["total_gross_irrigation_liters"] is None
    assert all(row["date"] >= "2026-10-10" for row in current["daily"])


def test_json_decimal_context_and_no_input_mutation(farm, forecast):
    original = deepcopy((farm, forecast))
    expected = calculate(farm, forecast)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        assert calculate(farm, forecast) == expected
        assert context.prec == 2
        assert context.rounding == ROUND_DOWN
    assert json.loads(json.dumps(expected, allow_nan=False)) == expected
    assert (farm, forecast) == original


def test_no_nonfinite_derived_json_values(farm, forecast):
    farm["area_m2"] = 1e308
    with pytest.raises(ValueError, match="Derived result"):
        calculate(farm, forecast)


def test_reference_and_freshness_settings_validation(farm, forecast):
    with pytest.raises(ValueError, match="reference_time"):
        calculate_irrigation(farm, forecast, reference_time=datetime(2026, 10, 10))
    with pytest.raises(ValueError, match="max_weather_age_hours"):
        calculate(farm, forecast, max_weather_age_hours=-1)


def test_confirmed_records_separate_from_proposed_and_no_demand_credit(farm, forecast):
    records = [{"id": "actual", "date": "2026-10-09", "applied_liters": 5000, "status": "confirmed"},
               {"id": "plan", "date": "2026-10-11", "applied_liters": 9000, "status": "planned"},
               {"id": "proposal", "date": "2026-10-12", "applied_liters": 1000, "status": "proposed"}]
    original = deepcopy(records)
    before = calculate(farm, forecast)
    result = summarize_irrigation_records(records)
    assert result["confirmed_applied_liters"] == 5000
    assert result["confirmed_count"] == 1
    assert result["unconfirmed_proposed_liters"] == 10000
    assert result["unconfirmed_count"] == 2
    assert result["confirmed_record_ids"] == ["actual"]
    assert records == original
    farm["irrigation_records"] = records
    assert calculate(farm, forecast) == before
    assert json.loads(json.dumps(result)) == result


def test_empty_records():
    result = summarize_irrigation_records([])
    assert result["confirmed_applied_liters"] == 0
    assert result["unconfirmed_count"] == 0


@pytest.mark.parametrize("field,value", [("id", ""), ("id", 1), ("id", " padded "), ("date", "2026-02-30"),
                                            ("applied_liters", -1), ("applied_liters", float("nan")),
                                            ("applied_liters", True), ("status", "unknown")])
def test_invalid_records(field, value):
    row = {"id": "record", "date": "2026-10-09", "applied_liters": 1000, "status": "confirmed"}
    row[field] = value
    with pytest.raises(ValueError):
        summarize_irrigation_records([row])


@pytest.mark.parametrize("field", ["id", "date", "applied_liters", "status"])
def test_missing_record_fields(field):
    row = {"id": "record", "date": "2026-10-09", "applied_liters": 1000, "status": "confirmed"}
    del row[field]
    with pytest.raises(ValueError, match="required"):
        summarize_irrigation_records([row])


def test_record_duplicates_across_statuses_rejected():
    row = {"id": "record", "date": "2026-10-09", "applied_liters": 1000, "status": "confirmed"}
    with pytest.raises(ValueError, match="duplicate"):
        summarize_irrigation_records([row, {**row, "status": "planned"}])
    with pytest.raises(ValueError):
        summarize_irrigation_records(None)
    with pytest.raises(ValueError):
        summarize_irrigation_records([None])


def test_exact_confirmed_record_documentation_example():
    root = Path(__file__).resolve().parents[1]
    example = json.loads((root / "docs/member3/irrigation_examples.json").read_text(encoding="utf-8"))["confirmed_records"]
    assert summarize_irrigation_records(example["request"]) == example["response"]


def test_existing_weather_adapter_cached_response_contract(farm):
    from backend.services.weather import normalize_weather_response
    root = Path(__file__).resolve().parents[1]
    saved = json.loads((root / "data/sample_weather.json").read_text(encoding="utf-8"))
    normalized = normalize_weather_response(saved["api_response"], saved["latitude"], saved["longitude"], saved["retrieved_at"], reference_time=NOW)
    normalized["status"] = "cached"
    result = calculate(farm, normalized)
    assert result["status"] == "partial"
    assert result["period_days"] == 7
    assert len(result["daily"]) == 6
    assert result["weather_provenance"]["status"] == "cached"
    assert result["summary"]["total_gross_irrigation_liters"] is None


def test_fully_valid_100_percent_efficiency_and_fractional_area(farm, forecast):
    farm["irrigation_efficiency"] = 1
    farm["area_m2"] = 0.1
    first = calculate(farm, forecast)["daily"][0]
    assert first["net_irrigation_liters"] == 0.575
    assert first["gross_irrigation_liters"] == 0.575


def test_missing_rain_not_silently_zero_even_with_zero_effective_fraction(farm, forecast):
    farm["effective_rain_fraction"] = 0
    forecast["daily"][0]["precipitation_mm"] = None
    first = calculate(farm, forecast)["daily"][0]
    assert first["etc_mm"] == 5.75
    assert first["effective_rain_mm"] is None
    assert first["net_irrigation_liters"] is None
