"""Resolve user-entered prices or curated Ministry wholesale observations.

No network calls. Historical fallback uses the median of deduplicated tomato
observations at most seven days old (age 0-7 inclusive of reference_date),
from exactly one market and in JOD/kg. Stale data is reported but never injected.
Only data_type='verified_wholesale' and HTTPS moa.gov.jo sources are eligible.
Those labels are a curation contract, not automatic proof of authenticity:
callers must pass reviewed records, never untrusted client-supplied market rows.
Synthetic fixtures are ineligible even if they contain an official-looking URL.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext
from urllib.parse import urlsplit

from .finance import _decimal_string, _parse_decimal


DEFAULT_MARKET = "Amman Central Market"
FRESHNESS_DAYS = 7


def _reference_date(value: str | date | None) -> date:
    if value is None:
        # Jordan's current civil offset; pass an explicit date for reproducibility.
        return datetime.now(timezone(timedelta(hours=3))).date()
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    raise ValueError("reference_date: must be an ISO YYYY-MM-DD date")


def _verified_row(row: dict) -> tuple[date, Decimal, str]:
    required = {"date", "crop", "market", "price_jod_per_kg", "source_url", "data_type"}
    if not isinstance(row, dict) or not required <= row.keys():
        raise ValueError("missing required market fields or invalid row type")
    if row["crop"] != "tomato":
        raise ValueError("crop must be tomato")
    if row["data_type"] != "verified_wholesale":
        raise ValueError("not a curated verified wholesale observation")
    if row.get("unit", "JOD/kg") != "JOD/kg":
        raise ValueError("unit must be JOD/kg; no unverified conversions are allowed")
    if not isinstance(row["market"], str) or not row["market"].strip():
        raise ValueError("market must be a nonblank string")
    if not isinstance(row["source_url"], str):
        raise ValueError("source_url must be a Ministry HTTPS URL")
    try:
        url = urlsplit(row["source_url"])
        host = url.hostname or ""
        if (url.scheme != "https" or not (host == "moa.gov.jo" or host.endswith(".moa.gov.jo"))
                or url.username or url.password or url.port not in (None, 443) or not url.path):
            raise ValueError("source_url must be a Ministry HTTPS URL")
    except ValueError as exc:
        raise ValueError("source_url must be a Ministry HTTPS URL") from exc
    # None is not a valid observation date, even though it is valid for as-of date.
    if not isinstance(row["date"], str):
        raise ValueError("date must be an ISO YYYY-MM-DD string")
    observed = _reference_date(row["date"])
    price = _parse_decimal(row["price_jod_per_kg"], "price_jod_per_kg", positive=True)
    return observed, price, row["source_url"]


def _median(prices: list[Decimal]) -> Decimal:
    ordered = sorted(prices)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    # Exact finite-decimal midpoint, independent of the caller's context.
    span = max(max(p.adjusted() + 1, 1) for p in prices) - min(min(p.as_tuple().exponent, 0) for p in prices)
    with localcontext(Context(prec=max(50, span + 10), Emax=MAX_EMAX, Emin=MIN_EMIN)):
        return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def resolve_tomato_price(
    farmer_price: str | None,
    market_records: list[dict],
    reference_date: str | date | None = None,
    *,
    market: str = DEFAULT_MARKET,
) -> dict:
    """Return JSON-compatible price provenance; bad rows become warnings.

    Farmer prices must be nonnegative decimal strings (explicit zero is valid).
    Official observations must be strictly positive. Invalid farmer/options
    raise ValueError; absent, malformed, synthetic, stale, and future-dated
    market observations yield unavailable references or exclusion warnings.
    """
    if farmer_price is not None:
        price = _parse_decimal(farmer_price, "farmer_price")
        return {
            "status": "resolved", "price_jod_per_kg": _decimal_string(price),
            "source": "farmer_entered", "source_urls": [], "market": None,
            "observation_start": None, "observation_end": None,
            "freshness": "not_applicable", "observation_count": 0,
            "explanation": "Explicit farmer price; not a verified completed sale or a market forecast.",
            "warnings": [],
        }
    as_of = _reference_date(reference_date)
    if not isinstance(market, str) or not market.strip():
        raise ValueError("market: must be a nonblank string")
    if not isinstance(market_records, list):
        raise ValueError("market_records: must be a list of curated observations")
    warnings, recent, stale, seen = [], [], [], set()
    for index, row in enumerate(market_records):
        try:
            observed, price, source_url = _verified_row(row)
        except ValueError as exc:
            warnings.append(f"market_records[{index}] excluded: {exc}")
            continue
        if row["market"] != market:
            warnings.append(f"market_records[{index}] excluded: different market")
            continue
        if observed > as_of:
            warnings.append(f"market_records[{index}] excluded: observation is after reference_date")
            continue
        identity = (observed, market, price, source_url)
        if identity in seen:
            warnings.append(f"market_records[{index}] excluded: duplicate observation")
            continue
        seen.add(identity)
        (recent if (as_of - observed).days <= FRESHNESS_DAYS else stale).append((observed, price, source_url))
    selected = recent or stale
    result = {
        "status": "resolved" if recent else "unavailable",
        "price_jod_per_kg": _decimal_string(_median([r[1] for r in recent])) if recent else None,
        "source": "ministry_wholesale_reference" if selected else None,
        "source_urls": sorted({r[2] for r in selected}), "market": market,
        "observation_start": min(r[0] for r in selected).isoformat() if selected else None,
        "observation_end": max(r[0] for r in selected).isoformat() if selected else None,
        "freshness": "recent" if recent else "stale" if stale else "unavailable",
        "observation_count": len(selected),
        "explanation": (
            "Median of recent curated wholesale observations; a reference estimate, not a farmgate price or guaranteed future price."
            if recent else "No recent verified tomato observation in this market and JOD/kg; selling price remains unknown."
        ),
        "warnings": warnings,
    }
    if recent:
        result["warnings"].append("Wholesale reference may differ from the farmer's net selling price; transport and commissions must be declared as costs.")
    elif stale:
        result["warnings"].append("Verified observations are stale (older than seven days); no price was injected.")
    return result
