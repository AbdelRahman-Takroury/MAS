from copy import deepcopy
import json

import pytest

from backend.engines.finance import calculate_financials
from backend.engines.finance_preparation import prepare_financials


@pytest.fixture
def unknown_price_inputs():
    return {
        "recorded_costs": [{"id": "incurred", "amount_jod": "500"}],
        "projected_costs": [{"id": "remaining", "amount_jod": "300"}],
        "actual_sales": [{"id": "sold", "quantity_kg": "100", "revenue_jod": "50"}],
        "future_sales": [{"id": "unsold", "quantity_kg": "1900"}],
    }


def test_global_farmer_price_fills_missing_without_mutation(unknown_price_inputs):
    original = deepcopy(unknown_price_inputs)
    result = prepare_financials(unknown_price_inputs, "0.6")
    assert result["status"] == "calculated"
    assert result["prepared_inputs"]["future_sales"][0]["price_jod_per_kg"] == "0.6"
    assert result["prepared_inputs"]["actual_sales"] == original["actual_sales"]
    assert result["financials"]["projected_total_revenue_jod"] == "1190"
    assert result["financials"]["projected_profit_jod"] == "390"
    assert result["price_references"]["unsold"]["source"] == "farmer_entered"
    assert unknown_price_inputs == original


def test_existing_per_sale_price_has_priority(unknown_price_inputs):
    unknown_price_inputs["future_sales"][0]["price_jod_per_kg"] = "0.700"
    result = prepare_financials(unknown_price_inputs, "0.6")
    assert result["prepared_inputs"] == unknown_price_inputs
    assert result["financials"]["projected_future_revenue_jod"] == "1330"


@pytest.mark.parametrize("missing", [True, False])
def test_unknown_price_returns_partial_without_invented_revenue(unknown_price_inputs, missing):
    if not missing:
        unknown_price_inputs["future_sales"][0]["price_jod_per_kg"] = None
    result = prepare_financials(unknown_price_inputs, reference_date="2026-10-09")
    assert result["status"] == "partial"
    assert result["prepared_inputs"] is None
    assert result["unresolved_future_sale_ids"] == ["unsold"]
    financials = result["financials"]
    assert financials["projected_total_costs_jod"] == "800"
    assert financials["projected_cost_per_kg_jod"] == "0.4"
    assert financials["actual_revenue_jod"] == "50"
    assert financials["actual_sold_kg"] == "100"
    assert financials["future_sale_kg"] == "1900"
    assert financials["required_future_break_even_price_jod_per_kg"] is not None
    for field in ("projected_future_revenue_jod", "projected_total_revenue_jod", "projected_profit_jod"):
        assert financials[field] is None
        assert "unknown" in financials["metric_explanations"][field]
    assert financials["warnings"]


def test_known_and_unknown_prices_still_mark_full_forecast_unavailable(unknown_price_inputs):
    unknown_price_inputs["future_sales"].append({"id": "known", "quantity_kg": "100", "price_jod_per_kg": "0.6"})
    result = prepare_financials(unknown_price_inputs)
    assert result["financials"]["projected_total_revenue_jod"] is None
    assert result["financials"]["total_marketable_quantity_kg"] == "2100"
    assert result["price_references"]["known"]["source"] == "farmer_entered"


def test_stale_and_synthetic_data_leave_price_unknown(unknown_price_inputs):
    rows = [{"date": "2026-09-01", "crop": "tomato", "market": "Amman Central Market",
             "price_jod_per_kg": "0.6", "source_url": "https://moa.gov.jo/bulletin.pdf", "data_type": "verified_wholesale"}]
    result = prepare_financials(unknown_price_inputs, market_records=rows, reference_date="2026-10-09")
    assert result["price_references"]["unsold"]["freshness"] == "stale"
    assert result["financials"]["projected_profit_jod"] is None
    rows[0].update(date="2026-10-09", data_type="synthetic_demo")
    assert prepare_financials(unknown_price_inputs, market_records=rows, reference_date="2026-10-09")["prepared_inputs"] is None


def test_empty_future_sales_need_no_price(unknown_price_inputs):
    unknown_price_inputs["future_sales"] = []
    result = prepare_financials(unknown_price_inputs)
    assert result["financials"] == calculate_financials(unknown_price_inputs)
    assert result["prepared_inputs"] == unknown_price_inputs
    assert result["price_references"] == {}


def test_explicit_zero_future_price_is_preserved(unknown_price_inputs):
    unknown_price_inputs["future_sales"][0]["price_jod_per_kg"] = "0"
    result = prepare_financials(unknown_price_inputs, "0.6")
    assert result["financials"]["projected_future_revenue_jod"] == "0"
    assert result["financials"]["projected_profit_jod"] == "-750"
    assert result["unresolved_future_sale_ids"] == []


@pytest.mark.parametrize("value", ["", "-1", "NaN", 0.6])
def test_malformed_present_price_is_not_treated_as_missing(unknown_price_inputs, value):
    unknown_price_inputs["future_sales"][0]["price_jod_per_kg"] = value
    with pytest.raises(ValueError, match="price_jod_per_kg"):
        prepare_financials(unknown_price_inputs, "0.6")


@pytest.mark.parametrize("group,field,value", [
    ("future_sales", "quantity_kg", "0"), ("actual_sales", "revenue_jod", "-1"),
    ("projected_costs", "amount_jod", "bad"), ("future_sales", "id", "sold"),
])
def test_other_engine_validation_remains_strict(unknown_price_inputs, group, field, value):
    unknown_price_inputs[group][0][field] = value
    with pytest.raises(ValueError):
        prepare_financials(unknown_price_inputs)


def test_missing_quantity_and_missing_lists_not_invented(unknown_price_inputs):
    del unknown_price_inputs["future_sales"][0]["quantity_kg"]
    with pytest.raises(ValueError, match="quantity_kg"):
        prepare_financials(unknown_price_inputs)
    with pytest.raises(ValueError, match="missing required"):
        prepare_financials({})


def test_preparation_json_serialization(unknown_price_inputs):
    for price in (None, "0.6"):
        result = prepare_financials(unknown_price_inputs, price, reference_date="2026-10-09")
        assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("value", [None, [], "bad"])
def test_preparation_request_type(value):
    with pytest.raises(ValueError, match="financial_inputs"):
        prepare_financials(value)


def test_bad_global_farmer_price_and_market_records(unknown_price_inputs):
    with pytest.raises(ValueError, match="farmer_price"):
        prepare_financials(unknown_price_inputs, "-1")
    with pytest.raises(ValueError, match="market_records"):
        prepare_financials(unknown_price_inputs, market_records={})


def test_resolved_global_price_applies_to_multiple_remaining_sales(unknown_price_inputs):
    unknown_price_inputs["future_sales"].append({"id": "second", "quantity_kg": "100"})
    original = deepcopy(unknown_price_inputs)
    result = prepare_financials(unknown_price_inputs, "0.6")
    assert result["financials"]["projected_future_revenue_jod"] == "1200"
    assert result["financials"]["projected_total_revenue_jod"] == "1250"
    assert result["financials"]["projected_profit_jod"] == "450"
    assert set(result["price_references"]) == {"unsold", "second"}
    assert unknown_price_inputs == original
