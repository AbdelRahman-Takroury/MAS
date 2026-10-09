"""Prepare missing future prices without weakening the strict finance contract."""

from copy import deepcopy
from datetime import date

from .finance import calculate_financials, _parse_decimal
from .price_reference import DEFAULT_MARKET, resolve_tomato_price


def prepare_financials(
    financial_inputs: dict,
    farmer_price: str | None = None,
    market_records: list[dict] | None = None,
    reference_date: str | date | None = None,
    *,
    market: str = DEFAULT_MARKET,
) -> dict:
    """Return prepared_inputs, financials, per-sale provenance, and unresolved IDs.

    Each existing future price is treated as explicit farmer input and preserved.
    A global farmer_price fills only missing/None prices, then verified market
    references are tried. Actual sales and every cost entry remain unchanged.
    If a price is unresolved, prepared_inputs is None and forecast revenue and
    profit are None with reasons. Costs, quantities, actual revenue, and break-even
    metrics remain available. The public financial engine remains strict.
    """
    if farmer_price is not None:
        _parse_decimal(farmer_price, "farmer_price")
    if not isinstance(financial_inputs, dict):
        raise ValueError("financial_inputs: must be an object")
    prepared = deepcopy(financial_inputs)
    future_sales = prepared.get("future_sales")
    if not isinstance(future_sales, list):
        # Reuse the engine's required-field/type error.
        calculate_financials(prepared)
    missing_indexes = []
    validation_inputs = deepcopy(prepared)
    for index, sale in enumerate(future_sales):
        if isinstance(sale, dict) and sale.get("price_jod_per_kg") is None:
            missing_indexes.append(index)
            # Private validation scaffold ONLY: never returned as a price or estimate.
            # All price-dependent results are suppressed if resolution fails.
            validation_inputs["future_sales"][index]["price_jod_per_kg"] = "0"
    financials = calculate_financials(validation_inputs)
    fallback = None
    if missing_indexes:
        fallback = resolve_tomato_price(
            farmer_price, [] if market_records is None else market_records,
            reference_date, market=market,
        )
    references, unresolved = {}, []
    for index, sale in enumerate(future_sales):
        reference = deepcopy(fallback) if index in missing_indexes else resolve_tomato_price(sale["price_jod_per_kg"], [])
        references[sale["id"]] = reference
        if reference["status"] == "resolved":
            # Preserve existing explicit price representations; fill only missing ones.
            if index in missing_indexes:
                sale["price_jod_per_kg"] = reference["price_jod_per_kg"]
        else:
            unresolved.append(sale["id"])
    if unresolved:
        reason = "Unavailable: selling price is unknown for future sales: " + ", ".join(unresolved) + "."
        for field in ("projected_future_revenue_jod", "projected_total_revenue_jod", "projected_profit_jod"):
            financials[field] = None
            financials["metric_explanations"][field] = reason
        financials["status"] = "partial"
        financials["warnings"].append(reason)
    else:
        financials = calculate_financials(prepared)
    for reference in references.values():
        for warning in reference["warnings"]:
            if warning not in financials["warnings"]:
                financials["warnings"].append(warning)
    return {
        "status": financials["status"],
        "prepared_inputs": None if unresolved else prepared,
        "financials": financials,
        "price_references": references,
        "unresolved_future_sale_ids": unresolved,
    }
