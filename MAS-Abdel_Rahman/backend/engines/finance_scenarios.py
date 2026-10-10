"""Explicit hypothetical future-price scenarios, reusing the Financial Engine."""

from copy import deepcopy
from decimal import Decimal

from .finance import calculate_financials, _parse_decimal, _decimal_string


def compare_selling_price(proposed_price: str | None, financials: dict) -> dict:
    """Compare JOD/kg with required FUTURE break-even, including prior revenue.

    Per-sale comparisons assume the proposed price applies to all future crop.
    Costs, including transport/commission, must already be declared in the engine
    inputs. This function never subtracts costs or claims guaranteed profit.
    """
    if not isinstance(financials, dict):
        raise ValueError("financials: must be an engine result object")
    price = _parse_decimal(proposed_price, "proposed_price") if proposed_price is not None else None
    threshold = financials.get("required_future_break_even_price_jod_per_kg")
    break_even = _parse_decimal(threshold, "required_future_break_even_price_jod_per_kg") if threshold is not None else None
    if price is None or break_even is None:
        message = "Cannot assess: insufficient inputs"
    elif price > break_even:
        message = "Above estimated break-even"
    elif price < break_even:
        message = "Below estimated break-even"
    else:
        message = "At estimated break-even"
    return {
        "message": message,
        "proposed_price_jod_per_kg": _decimal_string(price) if price is not None else None,
        "required_future_break_even_price_jod_per_kg": threshold,
        "basis": "Uniform future selling price versus remaining uncovered season costs per future kg.",
        "warnings": ["Estimated comparison only; not a guaranteed profit prediction."],
    }


def simulate_financial_scenarios(financial_inputs: dict, price_scenarios: dict) -> dict:
    """Use {'low': '0.300', 'base': '0.600', 'high': '0.900'} in JOD/kg.

    All three explicit nonnegative prices are mandatory. They replace only future
    prices; no percentages, quantities, costs, or historical revenues are invented.
    Unknown base prices can be omitted/None because each scenario explicitly
    supplies them. Other validation is delegated to calculate_financials().
    """
    if not isinstance(price_scenarios, dict) or set(price_scenarios) != {"low", "base", "high"}:
        raise ValueError("price_scenarios: must contain exactly low, base, and high decimal prices (JOD/kg)")
    prices = {key: _parse_decimal(price_scenarios[key], f"price_scenarios.{key}") for key in ("low", "base", "high")}
    if not prices["low"] <= prices["base"] <= prices["high"]:
        raise ValueError("price_scenarios: prices must satisfy low <= base <= high")
    if not isinstance(financial_inputs, dict):
        raise ValueError("financial_inputs: must be an object")
    scenarios = {}
    for name, price in prices.items():
        inputs = deepcopy(financial_inputs)
        future_sales = inputs.get("future_sales")
        if isinstance(future_sales, list):
            for sale in future_sales:
                if isinstance(sale, dict):
                    # Reject malformed supplied prices, even when overriding them.
                    existing = sale.get("price_jod_per_kg")
                    if existing is not None:
                        _parse_decimal(existing, "future_sales.price_jod_per_kg")
                    sale["price_jod_per_kg"] = _decimal_string(price)
        financials = calculate_financials(inputs)
        comparison = compare_selling_price(_decimal_string(price), financials)
        profit = Decimal(financials["projected_profit_jod"])
        scenarios[name] = {
            "label": "hypothetical", "price_jod_per_kg": _decimal_string(price),
            "financials": financials, "break_even_comparison": comparison,
            "profit_or_loss": "profit" if profit > 0 else "loss" if profit < 0 else "break_even",
            "warnings": financials["warnings"] + comparison["warnings"] + ["Hypothetical scenario; not a statistically validated forecast."],
        }
    return {"status": "simulated", "scenarios": scenarios}
