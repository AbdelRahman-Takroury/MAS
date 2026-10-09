"""End-to-end checks using the actually curated source CSV and exact docs examples."""

import csv
import json
from pathlib import Path

import pytest

from backend.engines.finance import calculate_financials
from backend.engines.finance_preparation import prepare_financials
from backend.engines.finance_scenarios import simulate_financial_scenarios
from backend.engines.price_reference import resolve_tomato_price


ROOT = Path(__file__).resolve().parents[1]


def records():
    with (ROOT / "data/tomato_market_prices.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def unknown_price_inputs():
    return {"recorded_costs": [{"id": "incurred", "amount_jod": "500"}],
            "projected_costs": [{"id": "remaining", "amount_jod": "300"}],
            "actual_sales": [], "future_sales": [{"id": "unsold", "quantity_kg": "2000"}]}


def test_curated_csv_resolves_exact_reference():
    rows = records()
    assert len(rows) == 3
    assert {row["date"] for row in rows} == {"2026-10-05", "2026-10-06", "2026-10-07"}
    result = resolve_tomato_price(None, rows, "2026-10-09")
    assert result["status"] == "resolved"
    assert result["price_jod_per_kg"] == "0.15"
    assert result["freshness"] == "recent"
    assert result["observation_count"] == 3
    assert result["observation_start"] == "2026-10-05"
    assert result["observation_end"] == "2026-10-07"


def test_verified_historical_example_works():
    result = prepare_financials(unknown_price_inputs(), market_records=records(), reference_date="2026-10-09")
    assert result["status"] == "calculated"
    assert result["financials"]["projected_total_costs_jod"] == "800"
    assert result["financials"]["projected_total_revenue_jod"] == "300"
    assert result["financials"]["projected_profit_jod"] == "-500"
    assert result["price_references"]["unsold"]["source"] == "ministry_wholesale_reference"
    assert "price_jod_per_kg" not in unknown_price_inputs()["future_sales"][0]


def test_farmer_overrides_actual_curated_reference():
    result = prepare_financials(unknown_price_inputs(), "0.600", records(), "2026-10-09")
    assert result["financials"]["projected_total_revenue_jod"] == "1200"
    assert result["financials"]["projected_profit_jod"] == "400"
    assert result["price_references"]["unsold"]["source"] == "farmer_entered"


def test_seed_data_expiration():
    assert resolve_tomato_price(None, records(), "2026-10-14")["status"] == "resolved"
    assert resolve_tomato_price(None, records(), "2026-10-15")["freshness"] == "stale"


@pytest.mark.parametrize("name", ["strict_engine", "farmer_price", "verified_reference", "unknown_price", "scenarios"])
def test_exact_documented_examples(name):
    examples = json.loads((ROOT / "docs/member3/financial_examples.json").read_text(encoding="utf-8"))
    example = examples[name]
    if name == "strict_engine":
        result = calculate_financials(example["request"])
    elif name == "scenarios":
        result = simulate_financial_scenarios(**example["request"])
    else:
        result = prepare_financials(**example["request"])
    assert result == example["response"]
    assert json.loads(json.dumps(result, allow_nan=False)) == result
