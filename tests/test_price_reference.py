"""Constructed validation cases are mocks, not published market observations."""

from copy import deepcopy
import csv
from datetime import date, datetime
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from backend.engines.price_reference import resolve_tomato_price


def mock_row(price="0.6", day="2026-10-07", **overrides):
    """Mock the curated-record contract; never export these rows as official data."""
    return {
        "date": day, "crop": "tomato", "market": "Amman Central Market",
        "price_jod_per_kg": price,
        "source_url": f"https://moa.gov.jo/ebv4.0/root_storage/ar/eb_list_page/{int(day[-2:])}-10-2026.pdf",
        "data_type": "verified_wholesale", **overrides,
    }


def resolve(rows, **kwargs):
    return resolve_tomato_price(None, rows, "2026-10-09", **kwargs)


def test_farmer_price_has_priority_even_over_bad_reference_data():
    result = resolve_tomato_price("0.700", None, "bad-date")
    assert result["price_jod_per_kg"] == "0.7"
    assert result["source"] == "farmer_entered"
    assert result["market"] is None
    assert result["observation_start"] is None
    assert result["freshness"] == "not_applicable"


def test_explicit_zero_farmer_price_is_not_unknown():
    result = resolve_tomato_price("0", [])
    assert result["status"] == "resolved"
    assert result["price_jod_per_kg"] == "0"


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "", 0.6, 1, True, Decimal("1")])
def test_bad_farmer_price(value):
    with pytest.raises(ValueError, match="farmer_price"):
        resolve_tomato_price(value, [])


def test_recent_selection_does_not_mix_markets_units_or_future_dates():
    rows = [mock_row("0.8"), mock_row("99", "2026-10-01"),
            mock_row("22", market="Other market"), mock_row("55", unit="JOD/box"),
            mock_row("44", "2026-10-10")]
    result = resolve(rows)
    assert result["status"] == "resolved"
    assert result["price_jod_per_kg"] == "0.8"
    assert result["observation_count"] == 1
    assert result["observation_start"] == result["observation_end"] == "2026-10-07"
    assert result["freshness"] == "recent"
    assert "farmgate" in result["explanation"]


@pytest.mark.parametrize("prices,expected", [(["0.3", "0.8", "0.5"], "0.5"), (["0.3", "0.8"], "0.55")])
def test_exact_historical_median(prices, expected):
    rows = [mock_row(price, f"2026-10-{7 - i:02d}") for i, price in enumerate(prices)]
    result = resolve(rows)
    assert result["price_jod_per_kg"] == expected
    assert result["observation_count"] == len(prices)
    assert result["observation_start"] == f"2026-10-{8 - len(prices):02d}"
    assert result["observation_end"] == "2026-10-07"


def test_median_does_not_lose_long_decimal_precision():
    rows = [mock_row("0.123456789012345678901234567891"), mock_row("0.123456789012345678901234567893", "2026-10-06")]
    with localcontext() as context:
        context.prec = 2
        result = resolve(rows)
        assert context.prec == 2
    assert result["price_jod_per_kg"] == "0.123456789012345678901234567892"


def test_duplicate_observations_do_not_weight_the_median():
    row = mock_row("0.8")
    result = resolve([row, deepcopy(row), mock_row("0.2", "2026-10-06")])
    assert result["price_jod_per_kg"] == "0.5"
    assert result["observation_count"] == 2
    assert any("duplicate" in warning for warning in result["warnings"])


def test_absent_records_are_unavailable():
    result = resolve([])
    assert result["status"] == "unavailable"
    assert result["price_jod_per_kg"] is None
    assert result["freshness"] == "unavailable"
    assert result["observation_start"] is None
    assert "unknown" in result["explanation"]


def test_stale_records_are_not_injected():
    result = resolve([mock_row("0.6", "2026-10-01")])
    assert result["status"] == "unavailable"
    assert result["price_jod_per_kg"] is None
    assert result["freshness"] == "stale"
    assert result["observation_end"] == "2026-10-01"
    assert any("stale" in warning for warning in result["warnings"])


def test_exact_freshness_boundary():
    assert resolve([mock_row(day="2026-10-02")])["status"] == "resolved"
    assert resolve([mock_row(day="2026-10-01")])["status"] == "unavailable"


def test_synthetic_fixture_never_resolves_to_official_price():
    with (Path(__file__).parent / "fixtures/synthetic_tomato_market_prices.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = resolve(rows)
    assert result["status"] == "unavailable"
    assert result["source"] is None
    rows[0]["source_url"] = "https://moa.gov.jo/official-looking.pdf"
    assert resolve(rows)["status"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("price_jod_per_kg", "0"), ("price_jod_per_kg", "-1"),
    ("price_jod_per_kg", "NaN"), ("price_jod_per_kg", "Infinity"),
    ("price_jod_per_kg", "abc"), ("price_jod_per_kg", 0.6),
    ("date", None), ("date", "bad-date"), ("date", "2026-02-30"),
    ("crop", "potato"), ("market", ""), ("market", None),
    ("unit", "fils/kg"), ("unit", "JOD/tonne"),
    ("source_url", "https://moa.gov.jo.evil.example/a"),
    ("source_url", "http://moa.gov.jo/a"), ("source_url", "https://example.com/a"),
    ("source_url", "https://user@moa.gov.jo/a"), ("source_url", None),
    ("data_type", "unverified"), ("data_type", "synthetic_demo"),
])
def test_invalid_market_fields_are_excluded_with_reason(field, value):
    result = resolve([mock_row(**{field: value})])
    assert result["status"] == "unavailable"
    assert result["price_jod_per_kg"] is None
    assert result["warnings"][0].startswith("market_records[0] excluded:")


@pytest.mark.parametrize("row", [None, [], "bad", {}])
def test_invalid_row_shape(row):
    result = resolve([row])
    assert result["status"] == "unavailable"
    assert result["warnings"]


@pytest.mark.parametrize("key", ["date", "crop", "market", "price_jod_per_kg", "source_url", "data_type"])
def test_missing_market_fields(key):
    row = mock_row()
    del row[key]
    assert resolve([row])["status"] == "unavailable"


@pytest.mark.parametrize("day", ["", "20261009", "2026-10-9", datetime(2026, 10, 9), 1])
def test_invalid_reference_date(day):
    with pytest.raises(ValueError, match="reference_date"):
        resolve_tomato_price(None, [], day)


def test_explicit_date_object_is_supported():
    assert resolve_tomato_price(None, [mock_row()], date(2026, 10, 9))["price_jod_per_kg"] == "0.6"


def test_invalid_options():
    with pytest.raises(ValueError, match="market_records"):
        resolve_tomato_price(None, None, "2026-10-09")
    with pytest.raises(ValueError, match="market:"):
        resolve([], market="")


def test_resolver_json_serialization_and_no_mutation():
    rows = [mock_row()]
    original = deepcopy(rows)
    result = resolve(rows)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert rows == original
