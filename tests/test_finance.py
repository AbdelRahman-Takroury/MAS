"""Financial contract, validation, precision, and JSON integration tests."""

from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, getcontext, localcontext
import json

import pytest

from backend.engines.finance import calculate_financials, parse_financial_inputs


@pytest.fixture
def request_data():
    return {
        "recorded_costs": [
            {"id": "cost_001", "description": "Seeds and planting", "amount_jod": "300.000"},
            {"id": "cost_002", "description": "Labor", "amount_jod": "200.000"},
        ],
        "projected_costs": [
            {"id": "future_cost_001", "description": "Remaining expenses", "amount_jod": "300.000"},
        ],
        "actual_sales": [],
        "future_sales": [
            {"id": "future_sale_001", "quantity_kg": "2000", "price_jod_per_kg": "0.600"},
        ],
    }


def test_basic_projected_season(request_data):
    result = calculate_financials(request_data)
    assert result == {
        "status": "calculated",
        "recorded_costs_jod": "500",
        "projected_additional_costs_jod": "300",
        "projected_total_costs_jod": "800",
        "actual_sold_kg": "0",
        "future_sale_kg": "2000",
        "total_marketable_quantity_kg": "2000",
        "actual_revenue_jod": "0",
        "projected_future_revenue_jod": "1200",
        "projected_total_revenue_jod": "1200",
        "projected_cost_per_kg_jod": "0.4",
        "break_even_price_jod_per_kg": "0.4",
        "required_future_break_even_price_jod_per_kg": "0.4",
        "projected_profit_jod": "400",
        "metric_explanations": {
            "projected_cost_per_kg_jod": "Projected total costs divided by total marketable quantity (JOD/kg).",
            "break_even_price_jod_per_kg": "Average full-season selling price needed to cover projected total costs (JOD/kg).",
            "required_future_break_even_price_jod_per_kg": "Remaining uncovered projected costs divided by future sale quantity (JOD/kg).",
        },
        "warnings": [],
        "assumptions": [
            "Projected costs are additional future costs and exclude recorded costs.",
            "Future sales contain only remaining unsold marketable quantities and exclude actual sales.",
            "Unique IDs cannot establish whether physical harvest quantities overlap; the caller must verify this.",
            "Total marketable quantity is actual sold quantity plus forecast future sales, not a validated biological yield.",
            "All supplied costs and revenues use JOD; quantities use kg. Only declared entries are included.",
        ],
    }


def test_mixed_actual_and_future_sales(request_data):
    request_data["actual_sales"] = [
        {"id": "sale_001", "quantity_kg": "500", "revenue_jod": "350"},
        {"id": "sale_002", "quantity_kg": "500", "revenue_jod": "250"},
    ]
    result = calculate_financials(request_data)
    assert result["actual_revenue_jod"] == "600"
    assert result["projected_future_revenue_jod"] == "1200"
    assert result["projected_total_revenue_jod"] == "1800"
    assert result["actual_sold_kg"] == "1000"
    assert result["future_sale_kg"] == "2000"
    assert result["total_marketable_quantity_kg"] == "3000"
    assert Decimal(result["projected_cost_per_kg_jod"]) > Decimal("0.26666666666666666666666666666666666666666666666666")
    assert result["required_future_break_even_price_jod_per_kg"] == "0.1"
    assert result["projected_profit_jod"] == "1000"


def test_zero_declared_harvest(request_data):
    request_data["future_sales"] = []
    result = calculate_financials(request_data)
    assert result["status"] == "partial"
    assert result["total_marketable_quantity_kg"] == "0"
    assert result["projected_total_costs_jod"] == "800"
    assert result["projected_total_revenue_jod"] == "0"
    assert result["projected_profit_jod"] == "-800"
    for metric in ("projected_cost_per_kg_jod", "break_even_price_jod_per_kg",
                   "required_future_break_even_price_jod_per_kg"):
        assert result[metric] is None
        assert result["metric_explanations"][metric].startswith("Unavailable:")
    assert len(result["warnings"]) == 2


def test_actual_only_sales(request_data):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1000", "revenue_jod": "900"}]
    request_data["future_sales"] = []
    result = calculate_financials(request_data)
    assert result["status"] == "partial"
    assert result["projected_cost_per_kg_jod"] == "0.8"
    assert result["break_even_price_jod_per_kg"] == "0.8"
    assert result["required_future_break_even_price_jod_per_kg"] is None
    assert result["projected_profit_jod"] == "100"


@pytest.mark.parametrize("field", ["recorded_costs", "projected_costs", "actual_sales", "future_sales"])
def test_missing_top_level_list_is_unknown_not_zero(request_data, field):
    del request_data[field]
    with pytest.raises(ValueError, match=f"missing required fields: {field}"):
        calculate_financials(request_data)


@pytest.mark.parametrize("field", ["recorded_costs", "projected_costs", "actual_sales", "future_sales"])
@pytest.mark.parametrize("value", [None, {}, "", 0, ()])
def test_invalid_list_types(request_data, field, value):
    request_data[field] = value
    with pytest.raises(ValueError, match=f"{field}: must be a list"):
        calculate_financials(request_data)


@pytest.mark.parametrize("value", [None, [], "", 1, True])
def test_request_must_be_dictionary(value):
    with pytest.raises(ValueError, match="must be an object"):
        calculate_financials(value)


NUMERIC_FIELDS = [
    ("recorded_costs", "amount_jod"),
    ("projected_costs", "amount_jod"),
    ("actual_sales", "quantity_kg"),
    ("actual_sales", "revenue_jod"),
    ("future_sales", "quantity_kg"),
    ("future_sales", "price_jod_per_kg"),
]


@pytest.mark.parametrize("group,field", NUMERIC_FIELDS)
@pytest.mark.parametrize("value", ["-1", "NaN", "sNaN", "Infinity", "-Infinity", "abc", "", " 1", "1 ", "1_000", "1,000", "1/3", 0.6, 1, True, None, Decimal("1")])
def test_invalid_numeric_values(request_data, group, field, value):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    request_data[group][0][field] = value
    with pytest.raises(ValueError, match=rf"{group}\[0\]\.{field}:"):
        calculate_financials(request_data)


@pytest.mark.parametrize("group,field", NUMERIC_FIELDS)
def test_missing_numeric_field(request_data, group, field):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    del request_data[group][0][field]
    with pytest.raises(ValueError, match=f"missing required fields: {field}"):
        calculate_financials(request_data)


@pytest.mark.parametrize("group", ["actual_sales", "future_sales"])
@pytest.mark.parametrize("value", ["0", "-0.000", "-2"])
def test_sale_quantity_must_be_positive(request_data, group, value):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    request_data[group][0]["quantity_kg"] = value
    with pytest.raises(ValueError, match="quantity_kg: must be positive"):
        calculate_financials(request_data)


@pytest.mark.parametrize("group", ["recorded_costs", "projected_costs", "actual_sales", "future_sales"])
@pytest.mark.parametrize("value", ["", " ", " padded ", None, 1, True])
def test_invalid_id(request_data, group, value):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    request_data[group][0]["id"] = value
    with pytest.raises(ValueError, match=r"\.id:"):
        calculate_financials(request_data)


@pytest.mark.parametrize("group", ["recorded_costs", "projected_costs", "actual_sales", "future_sales"])
def test_missing_id(request_data, group):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    del request_data[group][0]["id"]
    with pytest.raises(ValueError, match="missing required fields: id"):
        calculate_financials(request_data)


@pytest.mark.parametrize("group", ["recorded_costs", "projected_costs", "actual_sales", "future_sales"])
def test_duplicate_within_list(request_data, group):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    request_data[group].append(deepcopy(request_data[group][0]))
    with pytest.raises(ValueError, match="duplicate id"):
        calculate_financials(request_data)


@pytest.mark.parametrize("first,second", [("recorded_costs", "projected_costs"), ("actual_sales", "future_sales")])
def test_duplicate_across_actual_and_future(request_data, first, second):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "1"}]
    request_data[second][0]["id"] = request_data[first][0]["id"]
    with pytest.raises(ValueError, match="duplicate id"):
        calculate_financials(request_data)


def test_cost_and_sale_ids_have_separate_namespaces(request_data):
    request_data["future_sales"][0]["id"] = request_data["recorded_costs"][0]["id"]
    assert calculate_financials(request_data)["projected_profit_jod"] == "400"


@pytest.mark.parametrize("entry", [None, [], "cost", 1])
def test_entries_must_be_objects(request_data, entry):
    request_data["recorded_costs"][0] = entry
    with pytest.raises(ValueError, match="must be an object"):
        calculate_financials(request_data)


@pytest.mark.parametrize("description", [None, 1, [], True])
def test_optional_description_type(request_data, description):
    request_data["recorded_costs"][0]["description"] = description
    with pytest.raises(ValueError, match="description: must be a string"):
        calculate_financials(request_data)


def test_unknown_fields_rejected(request_data):
    request_data["future_sales"][0]["price_jod"] = "0.6"
    with pytest.raises(ValueError, match="unknown fields: price_jod"):
        calculate_financials(request_data)
    del request_data["future_sales"][0]["price_jod"]
    request_data["harvest"] = "2000"
    with pytest.raises(ValueError, match="unknown fields: harvest"):
        calculate_financials(request_data)


def test_fractional_precision(request_data):
    request_data["recorded_costs"] = [{"id": "a", "amount_jod": "0.1"}, {"id": "b", "amount_jod": "0.2"}]
    request_data["projected_costs"] = [{"id": "c", "amount_jod": "0.00001"}]
    request_data["future_sales"] = [{"id": "s", "quantity_kg": "3", "price_jod_per_kg": "0.100001"}]
    result = calculate_financials(request_data)
    assert result["recorded_costs_jod"] == "0.3"
    assert result["projected_total_costs_jod"] == "0.30001"
    assert result["projected_future_revenue_jod"] == "0.300003"
    assert result["projected_profit_jod"] == "-0.000007"


def test_large_and_small_amounts_are_not_rounded(request_data):
    request_data["recorded_costs"] = [
        {"id": "a", "amount_jod": "123456789012345678901234567890.123456789"},
        {"id": "b", "amount_jod": "0.000000001"},
    ]
    request_data["projected_costs"] = []
    request_data["future_sales"] = [{"id": "s", "quantity_kg": "1", "price_jod_per_kg": "123456789012345678901234567891.123456790"}]
    result = calculate_financials(request_data)
    assert result["projected_total_costs_jod"] == "123456789012345678901234567890.12345679"
    assert result["projected_profit_jod"] == "1"


def test_long_fractional_product_is_exact(request_data):
    request_data["recorded_costs"] = []
    request_data["projected_costs"] = []
    fraction = "0.12345678901234567890123456789"
    request_data["future_sales"] = [{"id": "s", "quantity_kg": fraction, "price_jod_per_kg": fraction}]
    result = calculate_financials(request_data)
    assert result["projected_future_revenue_jod"] == (
        "0.0152415787532388367504953515625361987875019051998750190521"
    )
    assert result["projected_profit_jod"] == result["projected_future_revenue_jod"]


def test_recurring_ratio_precision_and_context_independence(request_data):
    request_data["recorded_costs"] = [{"id": "a", "amount_jod": "1"}]
    request_data["projected_costs"] = []
    request_data["future_sales"] = [{"id": "s", "quantity_kg": "3", "price_jod_per_kg": "1"}]
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.clear_flags()
        before = context.copy()
        result = calculate_financials(request_data)
        assert getcontext().prec == before.prec
        assert getcontext().rounding == before.rounding
        assert getcontext().flags == before.flags
    assert result["projected_cost_per_kg_jod"] == "0." + "3" * 50
    assert result["required_future_break_even_price_jod_per_kg"] == "0." + "3" * 50


@pytest.mark.parametrize("revenue", ["800", "1000"])
def test_actual_revenue_covers_total_costs(request_data, revenue):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "100", "revenue_jod": revenue}]
    result = calculate_financials(request_data)
    assert result["required_future_break_even_price_jod_per_kg"] == "0"
    assert "already covers" in result["metric_explanations"]["required_future_break_even_price_jod_per_kg"]
    assert Decimal(result["projected_profit_jod"]) == Decimal(revenue) + Decimal("400")


def test_future_price_uses_total_costs_not_only_future_costs(request_data):
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "100", "revenue_jod": "400"}]
    assert calculate_financials(request_data)["required_future_break_even_price_jod_per_kg"] == "0.2"


def test_projected_loss(request_data):
    request_data["future_sales"][0]["price_jod_per_kg"] = "0.1"
    result = calculate_financials(request_data)
    assert result["projected_total_revenue_jod"] == "200"
    assert result["projected_profit_jod"] == "-600"


def test_all_empty_lists():
    result = calculate_financials({key: [] for key in ("recorded_costs", "projected_costs", "actual_sales", "future_sales")})
    assert result["status"] == "partial"
    for key in ("recorded_costs_jod", "projected_additional_costs_jod", "projected_total_costs_jod",
                "actual_sold_kg", "future_sale_kg", "total_marketable_quantity_kg", "actual_revenue_jod",
                "projected_future_revenue_jod", "projected_total_revenue_jod", "projected_profit_jod"):
        assert result[key] == "0"
    assert result["break_even_price_jod_per_kg"] is None


def test_zero_costs_and_zero_prices(request_data):
    request_data["recorded_costs"] = [{"id": "a", "amount_jod": "-0.000"}]
    request_data["projected_costs"] = []
    request_data["future_sales"][0]["price_jod_per_kg"] = "0"
    request_data["actual_sales"] = [{"id": "sold", "quantity_kg": "1", "revenue_jod": "0"}]
    result = calculate_financials(request_data)
    assert result["status"] == "calculated"
    for metric in ("projected_cost_per_kg_jod", "break_even_price_jod_per_kg",
                   "required_future_break_even_price_jod_per_kg", "projected_profit_jod"):
        assert result[metric] == "0"


def test_multiple_future_sales_and_exponent_strings(request_data):
    request_data["future_sales"] = [
        {"id": "a", "quantity_kg": "1e3", "price_jod_per_kg": ".5"},
        {"id": "b", "quantity_kg": "+1000", "price_jod_per_kg": "7e-1"},
    ]
    result = calculate_financials(request_data)
    assert result["future_sale_kg"] == "2000"
    assert result["projected_future_revenue_jod"] == "1200"


def test_json_round_trip_and_no_mutation(request_data):
    original = deepcopy(request_data)
    result = calculate_financials(json.loads(json.dumps(request_data)))
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result == calculate_financials(request_data)
    assert request_data == original
    for key, value in result.items():
        if key.endswith("_jod") or key.endswith("_kg"):
            assert isinstance(value, str) or value is None
    result["assumptions"].clear()
    assert calculate_financials(request_data)["assumptions"]


def test_internal_models_use_decimal(request_data):
    models = parse_financial_inputs(request_data)
    assert models.recorded_costs[0].amount_jod == Decimal("300.000")
    assert isinstance(models.recorded_costs[0].amount_jod, Decimal)
    assert models.future_sales[0].quantity_kg == Decimal("2000")
    assert models.future_sales[0].price_jod_per_kg == Decimal("0.600")
