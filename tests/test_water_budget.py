"""Pure mathematical water budget tests using synthetic weather contract mocks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from backend.engines.irrigation import calculate_irrigation
from backend.engines.water_budget import calculate_water_budget


NOW = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def irrigation():
    farm = {"crop": "tomato", "area_m2": 1000, "crop_stage": "mid_season", "irrigation_method": "drip", "irrigation_efficiency": 0.9}
    forecast = {"status": "live", "source": "open-meteo", "data_type": "forecast", "timezone": "Asia/Amman",
                "retrieved_at": "2026-10-10T09:00:00Z", "forecast_start_date": "2026-10-10", "forecast_end_date": "2026-10-10",
                "summary": {"requested_days": 1}, "units": {"et0": "mm/day", "precipitation": "mm"},
                "daily": [{"date": "2026-10-10", "et0_mm": 5, "precipitation_mm": 0}]}
    return calculate_irrigation(farm, forecast, reference_time=NOW)


def budget(irrigation, available, **kwargs):
    return calculate_water_budget(irrigation, available, reference_time=NOW, **kwargs)


def test_independent_5000_liter_shortage(irrigation):
    result = budget(irrigation, 5000)
    assert result["status"] == "calculated"
    assert result["water_status"] == "shortage"
    assert result["water_required_liters"] == pytest.approx(6388.888888888889)
    assert result["water_shortage_liters"] == pytest.approx(1388.888888888889)
    assert result["water_surplus_liters"] == 0
    assert result["coverage_percentage"] == pytest.approx(78.26086956521739)
    assert result["period_days"] == 1


def test_adequate_supply_and_capped_coverage(irrigation):
    result = budget(irrigation, 10000)
    assert result["water_status"] == "sufficient"
    assert result["coverage_percentage"] == 100
    assert result["water_shortage_liters"] == 0
    assert result["water_surplus_liters"] == pytest.approx(3611.111111111111)


def test_exact_equality(irrigation):
    result = budget(irrigation, irrigation["summary"]["total_gross_irrigation_liters"])
    assert result["water_status"] == "sufficient"
    assert result["water_shortage_liters"] == result["water_surplus_liters"] == 0
    assert result["coverage_percentage"] == 100


def test_zero_water_availability(irrigation):
    result = budget(irrigation, 0)
    assert result["water_status"] == "shortage"
    assert result["coverage_percentage"] == 0
    assert result["water_shortage_liters"] == result["water_required_liters"]


def test_zero_demand_does_not_divide_by_zero(irrigation):
    irrigation["daily"][0]["gross_irrigation_liters"] = 0
    irrigation["summary"]["total_gross_irrigation_liters"] = 0
    for available in (0, 1000):
        result = budget(irrigation, available)
        assert result["coverage_percentage"] == 100
        assert result["water_status"] == "sufficient"
        assert result["water_shortage_liters"] == 0
        assert result["water_surplus_liters"] == available
        assert any("convention" in assumption for assumption in result["assumptions"])


def test_missing_gross_demand_no_false_comparison(irrigation):
    irrigation["daily"][0]["gross_irrigation_liters"] = None
    irrigation["summary"]["total_gross_irrigation_liters"] = None
    irrigation["status"] = "partial"
    result = budget(irrigation, 100000)
    assert result["status"] == "partial"
    assert result["water_status"] == "unavailable"
    assert result["water_required_liters"] is result["coverage_percentage"] is None
    assert result["partial_assessment"] is None


def test_partial_period_does_not_claim_whole_period_sufficiency(irrigation):
    irrigation["period_days"] = irrigation["weather_provenance"]["requested_days"] = 7
    irrigation["period_end_date"] = irrigation["weather_provenance"]["period_end_date"] = "2026-10-16"
    irrigation["summary"]["total_gross_irrigation_liters"] = None
    irrigation["status"] = "partial"
    result = budget(irrigation, 100000)
    assert result["status"] == "partial"
    assert result["water_status"] == "unavailable"
    assert result["water_required_liters"] is result["water_shortage_liters"] is result["water_surplus_liters"] is None
    assert result["partial_assessment"]["scope"] == "known_dates_only"
    assert result["partial_assessment"]["covered_days"] == 1
    assert result["partial_assessment"]["requested_days"] == 7
    assert result["partial_assessment"]["water_status"] == "sufficient"


@pytest.mark.parametrize("available", [-1, float("nan"), float("inf"), "5000", True, None])
def test_invalid_available_water(irrigation, available):
    with pytest.raises(ValueError, match="water_available_liters"):
        budget(irrigation, available)


def test_period_dates_optional_and_must_match(irrigation):
    result = budget(irrigation, 5000, water_period_start_date="2026-10-10", water_period_end_date="2026-10-10")
    assert result["water_status"] == "shortage"
    assert not any("not independently supplied" in warning for warning in result["warnings"])
    with pytest.raises(ValueError, match="does not match"):
        budget(irrigation, 5000, water_period_start_date="2026-10-10", water_period_end_date="2026-10-16")
    with pytest.raises(ValueError, match="together"):
        budget(irrigation, 5000, water_period_start_date="2026-10-10")


def test_cached_weather_is_labelled_in_budget(irrigation):
    irrigation["weather_provenance"]["status"] = "cached"
    result = budget(irrigation, 5000)
    assert result["weather_provenance"]["status"] == "cached"
    assert any("cached" in warning for warning in result["warnings"])


def test_weather_expired_between_irrigation_and_budget(irrigation):
    result = calculate_water_budget(irrigation, 5000, reference_time=NOW + timedelta(days=2))
    assert result["status"] == "unavailable"
    assert result["coverage_percentage"] is None


@pytest.mark.parametrize("change", ["dates", "provenance", "units", "duplicate", "negative", "total", "missing_summary", "mismatched_provenance", "expired"])
def test_invalid_irrigation_results_not_compared(irrigation, change):
    if change == "dates":
        irrigation["period_end_date"] = "2026-10-16"
    elif change == "provenance":
        irrigation["weather_provenance"] = None
    elif change == "units":
        irrigation["units"]["volume"] = "m3"
    elif change == "duplicate":
        irrigation["daily"].append(deepcopy(irrigation["daily"][0]))
    elif change == "negative":
        irrigation["daily"][0]["gross_irrigation_liters"] = -1
    elif change == "total":
        irrigation["summary"]["total_gross_irrigation_liters"] = 1
    elif change == "missing_summary":
        del irrigation["summary"]
    elif change == "mismatched_provenance":
        irrigation["weather_provenance"]["period_start_date"] = "2026-10-11"
    else:
        irrigation["weather_provenance"]["valid_until"] = "2026-10-09T12:00:00Z"
    result = budget(irrigation, 5000)
    assert result["status"] == "unavailable"
    assert result["water_status"] == "unavailable"
    assert result["warnings"]


def test_unavailable_irrigation_returns_unavailable_budget(irrigation):
    irrigation["status"] = "unavailable"
    assert budget(irrigation, 5000)["water_status"] == "unavailable"


def test_request_types_and_invalid_status(irrigation):
    with pytest.raises(ValueError, match="irrigation_result"):
        budget(None, 5000)
    irrigation["status"] = "bad"
    with pytest.raises(ValueError, match="status"):
        budget(irrigation, 5000)


def test_budget_json_serialization_and_no_mutation(irrigation):
    original = deepcopy(irrigation)
    result = budget(irrigation, 5000)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert irrigation == original


@pytest.mark.parametrize("name", ["complete_weather", "shortage", "sufficient", "missing_efficiency", "missing_et0", "cached_partial", "expired", "runtime", "mathematical_one_day"])
def test_executed_documentation_examples(name):
    root = Path(__file__).resolve().parents[1]
    examples = json.loads((root / "docs/member3/irrigation_examples.json").read_text(encoding="utf-8"))
    item = examples[name]
    reference = datetime.fromisoformat(item["request"]["reference_time"].replace("Z", "+00:00"))
    result = calculate_irrigation(item["request"]["farm"], item["request"]["weather"], reference_time=reference)
    assert result == item["response"]["irrigation"]
    assert calculate_water_budget(result, item["request"]["water_available_liters"], reference_time=reference) == item["response"]["water_budget"]
