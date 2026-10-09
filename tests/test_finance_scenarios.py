from copy import deepcopy
import json

import pytest

from backend.engines.finance import calculate_financials
from backend.engines.finance_scenarios import compare_selling_price, simulate_financial_scenarios


@pytest.fixture
def scenario_inputs():
    return {
        "recorded_costs": [{"id": "incurred", "amount_jod": "500"}],
        "projected_costs": [
            {"id": "remaining", "amount_jod": "200"},
            {"id": "transport", "description": "Transport", "amount_jod": "60"},
            {"id": "commission", "description": "Commission", "amount_jod": "40"},
        ],
        "actual_sales": [{"id": "sold", "quantity_kg": "500", "revenue_jod": "300"}],
        "future_sales": [{"id": "unsold", "quantity_kg": "2000", "price_jod_per_kg": "0.6"}],
    }


PRICES = {"low": "0.2", "base": "0.6", "high": "0.9"}


def test_scenarios_preserve_actual_sales_and_count_selling_costs_once(scenario_inputs):
    original = deepcopy(scenario_inputs)
    result = simulate_financial_scenarios(scenario_inputs, PRICES)
    expected = {"low": ("700", "-100", "loss", "Below estimated break-even"),
                "base": ("1500", "700", "profit", "Above estimated break-even"),
                "high": ("2100", "1300", "profit", "Above estimated break-even")}
    for name, (revenue, profit, sign, message) in expected.items():
        scenario = result["scenarios"][name]
        assert scenario["label"] == "hypothetical"
        assert scenario["financials"]["actual_revenue_jod"] == "300"
        assert scenario["financials"]["actual_sold_kg"] == "500"
        assert scenario["financials"]["projected_total_costs_jod"] == "800"
        assert scenario["financials"]["projected_additional_costs_jod"] == "300"
        assert scenario["financials"]["projected_total_revenue_jod"] == revenue
        assert scenario["financials"]["projected_profit_jod"] == profit
        assert scenario["profit_or_loss"] == sign
        assert scenario["break_even_comparison"]["message"] == message
        assert scenario["warnings"]
    assert scenario_inputs == original


def test_scenarios_call_existing_engine_with_only_future_prices_changed(scenario_inputs, monkeypatch):
    from backend.engines import finance_scenarios
    calls = []
    def tracked(inputs):
        calls.append(deepcopy(inputs))
        return calculate_financials(inputs)
    monkeypatch.setattr(finance_scenarios, "calculate_financials", tracked)
    result = simulate_financial_scenarios(scenario_inputs, PRICES)
    assert len(calls) == 3
    for name, inputs in zip(("low", "base", "high"), calls):
        expected = deepcopy(scenario_inputs)
        expected["future_sales"][0]["price_jod_per_kg"] = PRICES[name]
        assert inputs == expected
        assert result["scenarios"][name]["financials"] == calculate_financials(expected)


def test_scenarios_support_unknown_original_price(scenario_inputs):
    del scenario_inputs["future_sales"][0]["price_jod_per_kg"]
    result = simulate_financial_scenarios(scenario_inputs, PRICES)
    assert result["scenarios"]["base"]["financials"]["projected_profit_jod"] == "700"
    assert "price_jod_per_kg" not in scenario_inputs["future_sales"][0]


@pytest.mark.parametrize("prices", [None, {}, {"base": "0.6"}, {**PRICES, "extra": "1"},
                                         {**PRICES, "low": "-1"}, {**PRICES, "base": 0.6},
                                         {**PRICES, "high": "NaN"}, {**PRICES, "low": "2"}])
def test_invalid_scenario_prices(scenario_inputs, prices):
    with pytest.raises(ValueError, match="price_scenarios"):
        simulate_financial_scenarios(scenario_inputs, prices)


def test_zero_and_equal_scenario_prices(scenario_inputs):
    result = simulate_financial_scenarios(scenario_inputs, {key: "0" for key in PRICES})
    for scenario in result["scenarios"].values():
        assert scenario["financials"]["projected_profit_jod"] == "-500"


def test_exact_break_even_scenario(scenario_inputs):
    result = simulate_financial_scenarios(scenario_inputs, {key: "0.25" for key in PRICES})
    assert result["scenarios"]["base"]["profit_or_loss"] == "break_even"
    assert result["scenarios"]["base"]["break_even_comparison"]["message"] == "At estimated break-even"


def test_no_future_crop_does_not_invent_quantity(scenario_inputs):
    scenario_inputs["future_sales"] = []
    result = simulate_financial_scenarios(scenario_inputs, PRICES)
    for scenario in result["scenarios"].values():
        assert scenario["financials"]["projected_total_revenue_jod"] == "300"
        assert scenario["financials"]["future_sale_kg"] == "0"
        assert scenario["break_even_comparison"]["message"] == "Cannot assess: insufficient inputs"


def test_duplicate_selling_costs_are_rejected(scenario_inputs):
    scenario_inputs["recorded_costs"].append(deepcopy(scenario_inputs["projected_costs"][1]))
    with pytest.raises(ValueError, match="duplicate id 'transport'"):
        simulate_financial_scenarios(scenario_inputs, PRICES)


def test_malformed_original_price_is_rejected(scenario_inputs):
    scenario_inputs["future_sales"][0]["price_jod_per_kg"] = "bad"
    with pytest.raises(ValueError, match="price_jod_per_kg"):
        simulate_financial_scenarios(scenario_inputs, PRICES)


def test_missing_future_quantity_rejected(scenario_inputs):
    del scenario_inputs["future_sales"][0]["quantity_kg"]
    with pytest.raises(ValueError, match="quantity_kg"):
        simulate_financial_scenarios(scenario_inputs, PRICES)


def test_comparison_uses_required_future_price_including_actual_revenue(scenario_inputs):
    financials = calculate_financials(scenario_inputs)
    assert financials["required_future_break_even_price_jod_per_kg"] == "0.25"
    assert financials["break_even_price_jod_per_kg"] == "0.32"
    assert compare_selling_price("0.3", financials)["message"] == "Above estimated break-even"
    assert compare_selling_price(None, financials)["message"] == "Cannot assess: insufficient inputs"


def test_comparison_when_actual_revenue_covers_costs(scenario_inputs):
    scenario_inputs["actual_sales"][0]["revenue_jod"] = "900"
    assert compare_selling_price("0", calculate_financials(scenario_inputs))["message"] == "At estimated break-even"


def test_scenarios_json_serialization(scenario_inputs):
    result = simulate_financial_scenarios(scenario_inputs, PRICES)
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_comparison_requires_result_dictionary():
    with pytest.raises(ValueError, match="financials"):
        compare_selling_price("0.6", None)
    assert compare_selling_price("0.6", {})["message"] == "Cannot assess: insufficient inputs"


def test_scenario_request_requires_dictionary():
    with pytest.raises(ValueError, match="financial_inputs"):
        simulate_financial_scenarios(None, PRICES)


def test_malformed_actual_sales_remain_errors(scenario_inputs):
    del scenario_inputs["actual_sales"][0]["revenue_jod"]
    with pytest.raises(ValueError, match="revenue_jod"):
        simulate_financial_scenarios(scenario_inputs, PRICES)
