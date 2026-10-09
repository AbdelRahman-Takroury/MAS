# Member 3 financial integration

Python 3.10+, standard library only. Run imports from the repository root. There
are no network calls, FastAPI endpoints, database dependencies, or scheduled jobs.

## Public functions

```python
from backend.engines.finance import calculate_financials
from backend.engines.price_reference import resolve_tomato_price
from backend.engines.finance_preparation import prepare_financials
from backend.engines.finance_scenarios import (
    simulate_financial_scenarios, compare_selling_price,
)
```

`calculate_financials(financial_inputs: dict) -> dict` is unchanged. All four
lists are required: `recorded_costs`, `projected_costs`, `actual_sales`,
`future_sales`. Cost entries require `id`, `amount_jod`; actual sales require
`id`, `quantity_kg`, `revenue_jod`; future sales require `id`, `quantity_kg`,
`price_jod_per_kg`. Every entry may have an optional string `description`.
All numeric values must be finite decimal strings. Nonnegative costs, revenue,
and prices are allowed; sale quantities must be positive. Unknown fields are
rejected. Missing lists are unknown information, not zero; explicit `[]` means
no declared entries. IDs must be unique across both cost lists and separately
across both sales lists. IDs cannot prove physical crop/cost entries do not overlap.

The response has `status`, all cost/revenue/profit totals and kg quantities,
three break-even/cost-per-kg ratios, `metric_explanations`, `warnings`, and
`assumptions`; the exact field names are shown in the examples linked below.
Numeric outputs are decimal strings; unavailable ratios are JSON `null`.
`calculated` means all ratios are available, `partial` means some are not.
Costs/quantities/revenues can still be known when ratios are unavailable.
Invalid input raises `ValueError` with a field path; Member 2 can map it to
HTTP 422 without adding business formulas to API routes.

## Optional price preparation

`prepare_financials(financial_inputs, farmer_price=None, market_records=None,
reference_date=None, *, market="Amman Central Market") -> dict` accepts missing
or `null` future prices, then calls the unchanged engine. Existing per-sale
prices are preserved as explicit farmer input. Global `farmer_price` applies
only to entries with unknown prices; it overrides any market fallback. Explicit
zero is a price, not missing data. Malformed/negative supplied prices remain errors.

```python
import csv
from pathlib import Path

# Load reviewed server-owned rows, never rows supplied by an untrusted client.
csv_path = Path("data/tomato_market_prices.csv")
with csv_path.open(encoding="utf-8", newline="") as stream:
    records = list(csv.DictReader(stream))

prepared = prepare_financials(
    financial_inputs,
    farmer_price=farmer_price,  # decimal string or None
    market_records=records,
    reference_date="2026-10-09",  # actual as-of date, not a fixed production default
)
```

The response envelope is:

| Field | Meaning |
| --- | --- |
| `status` | `calculated` or `partial`, following the financial results |
| `prepared_inputs` | Valid strict-engine request, or `null` if any price remains unknown |
| `financials` | Engine results, with forecast revenue/profit `null` when a price is unknown |
| `price_references` | Mapping of future sale ID to resolution metadata |
| `unresolved_future_sale_ids` | IDs whose price could not be resolved |

When resolution fails, costs, quantities, actual revenue, cost/kg and break-even
remain available if their required inputs exist. Future revenue, total projected
revenue and projected profit are withheld as `null`, with field-specific reasons.
No zero price estimate is returned. Internally, preparation uses a private zero-price
validation scaffold to reuse engine validation and price-independent formulas;
its price-dependent results are always suppressed if any price is unresolved.
Do not pass a `null` prepared request into the strict engine or scenario simulator.
Past actual sales are never changed. Inputs are copied, never modified in place.

## Resolver contract and provenance

`resolve_tomato_price(farmer_price, market_records, reference_date=None,
*, market="Amman Central Market") -> dict` gives explicit farmer prices priority.
Otherwise it selects deduplicated observations from the named market, crop
`tomato`, in JOD/kg, with dates no later than the as-of date and at most seven
days old (age 0-7 inclusive). The result is their exact Decimal median, not the
average of the bulletin's low/high columns. It never combines different markets
or units. An optional record `unit` must equal `JOD/kg`; other units are rejected.
All CSV rows use the fixed six-column schema; `price_jod_per_kg` identifies the unit.

Only `data_type: verified_wholesale` and HTTPS Ministry (`moa.gov.jo` or its
subdomains) source URLs are eligible. These labels do not authenticate a row:
the backend must load data that has actually been reviewed. Invalid rows are
excluded with indexed warnings. Bad farmer prices/options raise `ValueError`.
Synthetic/unverified data are excluded even with official-looking URLs.

Resolution fields are `status` (`resolved`/`unavailable`), `price_jod_per_kg`,
`source` (`farmer_entered`, `ministry_wholesale_reference`, or `null`),
`source_urls`, `market`, `observation_start`, `observation_end`, `freshness`,
`observation_count`, `explanation`, and `warnings`.
Freshness is `recent`, `stale`, `unavailable`, or `not_applicable` for user prices.
Stale observations retain provenance but return no usable price. If no date is
passed, the current date at UTC+03:00 is used; pass the actual Jordan as-of date
explicitly for deterministic runs and if timezone rules change.

### Verified seed data, reviewed 2026-10-09

The [Ministry listing](https://moa.gov.jo/AR/List/التجارة_الخارجية_والاسواق)
links the following Amman Central Market bulletins. Their full pages were rendered
and visually checked against extracted text. We transcribed the plain tomato
row (`بندورة`), column `أغلب` (prevailing price), not the separate hanging-tomato
row (`بندورة معلقة`), and not the quantity or daily-requirement columns.

| Observation | Low / prevailing / high, qirsh/kg | Selected JOD/kg | Source |
| --- | --- | --- | --- |
| 2026-10-05 | 10 / 15 / 20 | 0.150 | [Bulletin](https://moa.gov.jo/ebv4.0/root_storage/ar/eb_list_page/5-10-2026.pdf) |
| 2026-10-06 | 8 / 15 / 20 | 0.150 | [Bulletin](https://moa.gov.jo/ebv4.0/root_storage/ar/eb_list_page/6-10-2026.pdf) |
| 2026-10-07 | 7 / 15 / 20 | 0.150 | [Bulletin](https://moa.gov.jo/ebv4.0/root_storage/ar/eb_list_page/7-10-2026.pdf) |

The bulletin header explicitly gives qirsh/kg. Conversion is 15 / 100 = 0.150
JOD/kg; [Jordan Customs](https://www.customs.gov.jo/AR/Pages/عن_الاردن) confirms
one JOD equals 100 qirsh. Only these three verified observations are in the
production CSV. Synthetic demo data are isolated in
`tests/fixtures/synthetic_tomato_market_prices.csv` and never used as references.
For as-of 2026-10-09 the median is 0.150 JOD/kg. The seed data become unavailable
after 2026-10-14 unless newer reviewed observations are supplied.

These are wholesale references, not actual farmgate selling prices or net
receipts. Crop grade, subtype, and farmer-specific terms are not independently
verified; use an explicit farmer price if the plain tomato reference is unsuitable.
No live/current or future price guarantee is made. The finite CSV requires manual
updates; no scraping or updater has been added.

## Hypothetical scenarios and selling costs

```python
scenarios = simulate_financial_scenarios(
    financial_inputs,
    {"low": "0.300", "base": "0.600", "high": "0.900"},
)
```

All three decimal-string prices must satisfy low <= base <= high. Each applies
uniformly to all future sale quantities. Unknown original future prices may be
omitted/`null` because scenarios explicitly supply prices; malformed supplied
prices are rejected. No quantities are estimated. Costs, actual sales, and actual
revenue are copied unchanged. Each scenario calls `calculate_financials()` and
returns `label: hypothetical`, `price_jod_per_kg`, full `financials`,
`profit_or_loss` (`profit`, `loss`, `break_even`), `break_even_comparison`, and
`warnings`. The envelope is `{"status": "simulated", "scenarios": {...}}`.
These are user-defined cases, not statistically validated forecasts.

`compare_selling_price(price_or_none, financials)` compares the proposed uniform
future JOD/kg price with `required_future_break_even_price_jod_per_kg`, which
credits actual revenue already received. It reports above/below/at estimated
break-even, or insufficient inputs. This is not a guaranteed profit prediction.

Transportation, commissions, packaging, and other selling expenses go into the
existing cost lists once, with distinct IDs. Incurred expenses belong in recorded
costs; additional expected expenses belong in projected costs. Do not send a
second selling-cost deduction. If commission is percentage-based, the caller
must supply a justified JOD estimate; this module does not infer commission
terms or vary cost estimates with scenario revenue. Duplicated physical expenses
under different IDs cannot be detected automatically.

## Exact executed JSON examples and farmer information

[financial_examples.json](financial_examples.json) contains complete request and
response JSON pairs generated by this implementation: strict engine, farmer
price preparation, verified Ministry reference preparation, no available price,
and Low/Base/High scenarios. The examples are checked against current code in
pytest. In the 800 JOD / 2000 kg example, farmer price 0.600 yields revenue 1200
and profit 400; reference 0.150 yields revenue 300 and loss 500. Unknown price
keeps cost/kg 0.4 and withholds forecast revenue/profit.

Collect recorded costs, additional future costs including selling expenses,
completed sale quantities and actual gross revenue, remaining unsold marketable
quantities, expected price(s), and intended market/crop comparability. Actual
gross revenue and separately recorded selling expenses must use a consistent
basis to avoid deducting expenses twice. Collect unique IDs and independently
check for overlap. Never invent missing quantities, expenses, dates, or prices.

Monetary arithmetic uses Decimal. Finite sums/products preserve precision;
recurring ratios use at least 50 significant digits. Only the UI should apply
display rounding. Source freshness is date-based, not a confidence score. Market
reference quality and harvest projections are not independently validated by the
calculator. No fees, VAT, farmgate conversion, or unreported costs are inferred.

Run the entire suite with `python -B -m pytest -q -p no:cacheprovider` from the
repository root (pytest is a development dependency only).
