"""Season financial calculations in Jordanian dinars (JOD) and kilograms (kg).

Integration contract
--------------------
Call ``calculate_financials(financial_inputs: dict) -> dict``. No FastAPI,
database, network, or third-party dependencies are required. Invalid input
raises ValueError with the offending field path; callers can map this to HTTP
422. The input is never mutated.

All four request keys are required lists (an empty list is an explicit claim
of no declared entries; a missing list is unknown information and is rejected):

* recorded_costs / projected_costs: {id: str, amount_jod: decimal string,
  description?: str}. Projected costs are ADDITIONAL future costs only.
* actual_sales: {id: str, quantity_kg: decimal string,
  revenue_jod: decimal string, description?: str}. Completed transactions.
* future_sales: {id: str, quantity_kg: decimal string,
  price_jod_per_kg: decimal string, description?: str}. Remaining unsold crop.

IDs must be nonblank and unique across both cost lists, and separately across
both sale lists. Unknown keys are rejected to catch misspelled financial fields.
Numeric fields require finite decimal strings (including scientific notation).
Costs, revenue, and prices must be nonnegative; individual sale quantities must
be positive. Python floats, integers, booleans, and raw Decimals are rejected
at this JSON boundary. Explicit zero cost/revenue/price values are accepted.

Response keys are status; recorded_costs_jod; projected_additional_costs_jod;
projected_total_costs_jod; actual_sold_kg; future_sale_kg;
total_marketable_quantity_kg; actual_revenue_jod; projected_future_revenue_jod;
projected_total_revenue_jod; projected_cost_per_kg_jod;
break_even_price_jod_per_kg; required_future_break_even_price_jod_per_kg;
projected_profit_jod; metric_explanations; warnings; assumptions.
Every numeric result is a decimal string, except unavailable ratios are None
(JSON null). metric_explanations maps all three ratio keys to plain-language
definitions or unavailability reasons. warnings and assumptions are string lists.
Status is 'calculated' when all ratios are available, otherwise 'partial':
validated costs and revenues are still calculable even with no sale quantities.
Invalid/unknown requests raise ValueError rather than returning invented totals.

The full-season break-even price is total cost / total marketable quantity.
Required future break-even price is max(total cost - actual revenue, 0) /
future quantity. Actual revenue is included once. Marketable quantity means
actual sold plus declared future sales, not an independently verified yield.
Unique IDs cannot establish whether physical harvest quantities overlap, or
whether costs have been duplicated under different IDs. The caller must ensure
future sales exclude completed sales and future costs exclude incurred costs.

Precision: sums, products, and differences are exact for finite input decimals
using input-dependent local precision. Ratios use at least 50 significant
digits; recurring decimals necessarily have finite ROUND_HALF_EVEN precision.
No currency quantization or display rounding is performed. Display clients may
round JOD amounts to three decimal places. Trailing fractional zeros are removed
on serialization without changing the value. The caller's Decimal context is
neither used nor modified.

Example request (all numeric values are strings):
{
  "recorded_costs": [
    {"id": "cost_001", "description": "Seeds and planting", "amount_jod": "300.000"},
    {"id": "cost_002", "description": "Labor", "amount_jod": "200.000"}
  ],
  "projected_costs": [
    {"id": "future_cost_001", "description": "Remaining expenses", "amount_jod": "300.000"}
  ],
  "actual_sales": [],
  "future_sales": [
    {"id": "future_sale_001", "quantity_kg": "2000", "price_jod_per_kg": "0.600"}
  ]
}
This yields total costs '800', total revenue '1200', profit '400', and all
three per-kg metrics '0.4'. See tests/test_finance.py for exact response checks.
"""

from dataclasses import dataclass
from decimal import (
    Context, Decimal, InvalidOperation, MAX_EMAX, MIN_EMIN,
    ROUND_HALF_EVEN, localcontext,
)
import re
from typing import Any


@dataclass(frozen=True)
class CostItem:
    id: str
    amount_jod: Decimal
    description: str | None = None


@dataclass(frozen=True)
class SaleItem:
    id: str
    quantity_kg: Decimal
    revenue_jod: Decimal
    description: str | None = None


@dataclass(frozen=True)
class FutureSaleItem:
    id: str
    quantity_kg: Decimal
    price_jod_per_kg: Decimal
    description: str | None = None


@dataclass(frozen=True)
class FinancialInputs:
    recorded_costs: tuple[CostItem, ...]
    projected_costs: tuple[CostItem, ...]
    actual_sales: tuple[SaleItem, ...]
    future_sales: tuple[FutureSaleItem, ...]


_DECIMAL_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INPUT_KEYS = {"recorded_costs", "projected_costs", "actual_sales", "future_sales"}
_ASSUMPTIONS = (
    "Projected costs are additional future costs and exclude recorded costs.",
    "Future sales contain only remaining unsold marketable quantities and exclude actual sales.",
    "Unique IDs cannot establish whether physical harvest quantities overlap; the caller must verify this.",
    "Total marketable quantity is actual sold quantity plus forecast future sales, not a validated biological yield.",
    "All supplied costs and revenues use JOD; quantities use kg. Only declared entries are included.",
)


def _require_fields(data: dict, required: set[str], optional: set[str], path: str) -> None:
    missing = required - data.keys()
    if missing:
        raise ValueError(f"{path}: missing required fields: {', '.join(sorted(missing))}")
    unknown = data.keys() - required - optional
    if unknown:
        raise ValueError(f"{path}: unknown fields: {', '.join(sorted(map(str, unknown)))}")


def _parse_decimal(value: Any, path: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL_PATTERN.fullmatch(value):
        raise ValueError(f"{path}: must be a finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{path}: must be a finite decimal string") from exc
    if not number.is_finite():
        raise ValueError(f"{path}: must be finite")
    if number < 0 or (positive and number == 0):
        constraint = "positive" if positive else "nonnegative"
        raise ValueError(f"{path}: must be {constraint}")
    return number


def _parse_items(value: Any, kind: str) -> tuple:
    if not isinstance(value, list):
        raise ValueError(f"{kind}: must be a list; use [] only for explicitly no entries")
    fields = ({"amount_jod"} if kind.endswith("costs") else
              {"quantity_kg", "revenue_jod" if kind == "actual_sales" else "price_jod_per_kg"})
    model = CostItem if kind.endswith("costs") else SaleItem if kind == "actual_sales" else FutureSaleItem
    items = []
    for index, entry in enumerate(value):
        path = f"{kind}[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: must be an object")
        _require_fields(entry, fields | {"id"}, {"description"}, path)
        identifier = entry["id"]
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(f"{path}.id: must be a nonblank string")
        if identifier != identifier.strip():
            raise ValueError(f"{path}.id: must not have surrounding whitespace")
        if "description" in entry and not isinstance(entry["description"], str):
            raise ValueError(f"{path}.description: must be a string when supplied")
        numbers = {
            field: _parse_decimal(entry[field], f"{path}.{field}", positive=field == "quantity_kg")
            for field in sorted(fields)
        }
        items.append(model(id=identifier, description=entry.get("description"), **numbers))
    return tuple(items)


def _check_unique_ids(items: tuple, path: str) -> None:
    seen = set()
    for item in items:
        if item.id in seen:
            raise ValueError(f"{path}: duplicate id '{item.id}'")
        seen.add(item.id)


def parse_financial_inputs(financial_inputs: dict) -> FinancialInputs:
    """Validate the JSON request and build immutable Decimal-backed models."""
    if not isinstance(financial_inputs, dict):
        raise ValueError("financial_inputs: must be an object")
    _require_fields(financial_inputs, _INPUT_KEYS, set(), "financial_inputs")
    inputs = FinancialInputs(**{
        key: _parse_items(financial_inputs[key], key) for key in sorted(_INPUT_KEYS)
    })
    _check_unique_ids(inputs.recorded_costs + inputs.projected_costs, "recorded_costs/projected_costs")
    _check_unique_ids(inputs.actual_sales + inputs.future_sales, "actual_sales/future_sales")
    return inputs


def _calculation_precision(inputs: FinancialInputs) -> int:
    numbers = [item.amount_jod for item in inputs.recorded_costs + inputs.projected_costs]
    for item in inputs.actual_sales:
        numbers.extend((item.quantity_kg, item.revenue_jod))
    for item in inputs.future_sales:
        numbers.extend((item.quantity_kg, item.price_jod_per_kg))
    if not numbers:
        return 50
    # Products can double the exponent span; summation may add carry digits.
    lowest_exponent = min(min(number.as_tuple().exponent, 0) for number in numbers)
    highest_position = max(max(number.adjusted() + 1, 1) for number in numbers)
    return max(50, 2 * (highest_position - lowest_exponent) + len(str(len(numbers))) + 10)


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _calculate(inputs: FinancialInputs) -> dict:
    zero = Decimal("0")
    recorded_costs = sum((item.amount_jod for item in inputs.recorded_costs), zero)
    remaining_costs = sum((item.amount_jod for item in inputs.projected_costs), zero)
    total_costs = recorded_costs + remaining_costs
    actual_quantity = sum((item.quantity_kg for item in inputs.actual_sales), zero)
    future_quantity = sum((item.quantity_kg for item in inputs.future_sales), zero)
    total_quantity = actual_quantity + future_quantity
    actual_revenue = sum((item.revenue_jod for item in inputs.actual_sales), zero)
    future_revenue = sum((item.quantity_kg * item.price_jod_per_kg for item in inputs.future_sales), zero)
    total_revenue = actual_revenue + future_revenue
    average_price = total_costs / total_quantity if total_quantity else None
    uncovered_costs = max(total_costs - actual_revenue, zero)
    future_price = uncovered_costs / future_quantity if future_quantity else None

    warnings = []
    explanations = {
        "projected_cost_per_kg_jod": "Projected total costs divided by total marketable quantity (JOD/kg).",
        "break_even_price_jod_per_kg": "Average full-season selling price needed to cover projected total costs (JOD/kg).",
        "required_future_break_even_price_jod_per_kg": "Remaining uncovered projected costs divided by future sale quantity (JOD/kg).",
    }
    if not total_quantity:
        reason = "Unavailable: total marketable quantity is zero; no actual or future sale quantities were declared."
        explanations["projected_cost_per_kg_jod"] = reason
        explanations["break_even_price_jod_per_kg"] = reason
        warnings.append(reason)
    if not future_quantity:
        reason = "Unavailable: future sale quantity is zero; required future break-even price cannot be calculated."
        explanations["required_future_break_even_price_jod_per_kg"] = reason
        warnings.append(reason)
    elif uncovered_costs == 0:
        explanations["required_future_break_even_price_jod_per_kg"] = (
            "Required future break-even price is zero: actual revenue already covers projected total costs."
        )

    values = {
        "recorded_costs_jod": recorded_costs,
        "projected_additional_costs_jod": remaining_costs,
        "projected_total_costs_jod": total_costs,
        "actual_sold_kg": actual_quantity,
        "future_sale_kg": future_quantity,
        "total_marketable_quantity_kg": total_quantity,
        "actual_revenue_jod": actual_revenue,
        "projected_future_revenue_jod": future_revenue,
        "projected_total_revenue_jod": total_revenue,
        "projected_cost_per_kg_jod": average_price,
        "break_even_price_jod_per_kg": average_price,
        "required_future_break_even_price_jod_per_kg": future_price,
        "projected_profit_jod": total_revenue - total_costs,
    }
    return {
        "status": "calculated" if average_price is not None and future_price is not None else "partial",
        **{key: _decimal_string(value) if value is not None else None for key, value in values.items()},
        "metric_explanations": explanations,
        "warnings": warnings,
        "assumptions": list(_ASSUMPTIONS),
    }


def calculate_financials(financial_inputs: dict) -> dict:
    """Return JSON-compatible season financials, or raise ValueError on invalid input.

    All numeric inputs/outputs are decimal strings, with None for unavailable
    ratios. See the module docstring for the complete integration contract.
    """
    inputs = parse_financial_inputs(financial_inputs)
    with localcontext(Context(
        prec=_calculation_precision(inputs), rounding=ROUND_HALF_EVEN,
        Emax=MAX_EMAX, Emin=MIN_EMIN,
    )):
        return _calculate(inputs)
