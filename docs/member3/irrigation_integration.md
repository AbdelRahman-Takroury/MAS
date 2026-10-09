# Member 3 irrigation and water budget

Python 3.10+, standard library only. These modules consume normalized weather
and explicit farm assumptions; neither fetches weather, writes files, operates
pumps, or connects to a database. Existing financial/weather modules are unchanged.

## Member 2 integration

```python
from backend.services.weather import get_weather
from backend.engines.irrigation import calculate_irrigation, summarize_irrigation_records
from backend.engines.water_budget import calculate_water_budget

weather = get_weather(latitude, longitude)
irrigation = calculate_irrigation(farm, weather)
budget = calculate_water_budget(irrigation, water_available_liters)
```

The public two-argument calls are preserved. No new API endpoints or tables are
needed. Collect farm/available-water information, pass the existing weather
response, handle errors, and forward the JSON results. Member 1 may display the
daily breakdown, summaries, warnings, and budget indicator. Show provenance,
period dates, and partial coverage alongside any estimates.

## Farm request

```json
{
  "crop": "tomato",
  "area_m2": 1000,
  "crop_stage": "mid_season",
  "irrigation_method": "drip",
  "irrigation_efficiency": 0.90,
  "effective_rain_fraction": 0.80,
  "system_flow_liters_per_hour": 2000
}
```

This is a hypothetical open-field farm near Deir Alla, not a verified farm.
Only `tomato` and `drip` are supported. Area must be positive. Supported stages
are `initial`, `development`, `mid_season`, and `late_season`. Stage is required
unless an explicit positive `kc_override` is provided. Missing/null stage with
override is accepted; invalid stage names are rejected, not guessed.

Efficiency, rain effectiveness, system flow and Kc override are optional; missing
or `null` means unknown. When supplied, efficiency must be >0 and <=1, rain
fraction must be 0-1, and flow/override must be positive. Numeric inputs must be
finite JSON numbers (int/float, excluding bool); strings are not accepted. Extra
farm metadata are ignored; misspelling optional fields leaves the assumption
unknown rather than injecting a default. No efficiency, rainfall factor, flow,
crop calendar, or soil state is inferred.

Optional settings for `calculate_irrigation()` are:

| Keyword | Purpose |
| --- | --- |
| `kc_parameters=None` | Explicit mapping of supported stages to positive coefficients; unspecified stages keep documented reference estimates |
| `reference_time=None` | A timezone-aware datetime; defaults to current UTC time for freshness checks |
| `max_weather_age_hours=24.0` | Nonnegative weather-age limit, at most 168 hours; default matches the Weather Engine |

`reference_time` is for trusted backend-controlled historical replay/tests. Do
not let an untrusted client bypass expiry by choosing a past assessment time.

## Weather input contract

Use the existing [Weather Engine guide](weather_integration.md) and its actual
response. Fields consumed are:

```text
status: live or cached
source: open-meteo
data_type: forecast
timezone: Asia/Amman
retrieved_at: timezone-aware ISO timestamp
forecast_start_date, forecast_end_date: ISO YYYY-MM-DD
summary.requested_days: integer matching the inclusive requested period
units.et0: mm/day
units.precipitation: mm
daily: [{date, et0_mm, precipitation_mm, ...}, ...]
warnings: optional list
```

The adapter normally requests seven days. Explicitly dated 1-7 day projections
are also accepted when the start/end and `summary.requested_days` all agree.
Simply removing daily rows while retaining a seven-day request produces partial
coverage; it does not shrink the period. Rain probability is never substituted
for rainfall. Unrelated missing weather fields such as humidity do not prevent
irrigation calculations when ET0/rainfall are valid.

Weather must be a trusted backend adapter result. Provenance labels alone cannot
authenticate manually fabricated data. Labelled synthetic/non-forecast data,
unknown sources, invalid units/timestamps, unavailable weather, and expired
retrievals return unavailable demand, not invented ET0. Missing/negative/nonfinite
daily ET0 or rain become `null` with warnings and dependent metrics withheld.
Invalid dates/duplicates are excluded with warnings. No API calls occur here.

Cached status and original retrieval time remain visible downstream. Dates
before the current Amman date are excluded. Forecast rows beyond the original
retrieval's seven-day horizon cannot be used, even if a cached adapter's current
requested end date extends farther. After midnight, a still-fresh cached week
can therefore supply only six dates and must remain partial. The date boundary
uses the same current UTC+03:00 convention as the existing Weather Engine.

## Formulas and coefficients

```text
ETc_mm = ET0_mm * Kc
effective_rain_mm = precipitation_mm * explicit_effective_rain_fraction
net_irrigation_mm = max(ETc_mm - effective_rain_mm, 0)
crop_water_consumption_liters = ETc_mm * area_m2
net_irrigation_liters = net_irrigation_mm * area_m2
gross_irrigation_liters = net_irrigation_liters / explicit_irrigation_efficiency
runtime_hours = gross_irrigation_liters / explicit_system_flow_liters_per_hour
```

The volume conversion is 1 mm over 1 m2 = 1 liter. Zero rain gives zero effective
rain without needing a fraction. Positive/unknown rain without a known fraction
does not support a net irrigation estimate. Missing rain remains unknown even
when the supplied fraction is zero. Excess rain is capped against that day's
net demand only; it is not credited to other days.

[FAO-56 Chapter 6, Table 12](https://www.fao.org/4/X0490E/x0490e0b.htm)
provides tomato reference coefficients: initial 0.60, mid-season 1.15, and
end-stage range 0.70-0.90. The MVP uses a development midpoint of 0.875 and a
fixed late-season estimate of 0.80. Development is an approximation, not a fixed
universal FAO coefficient; late-season decline is not simulated. The stage/Kc
remains constant throughout the requested period. Response `kc` exposes value,
stage, source, source URL, and explanation. Explicit configured coefficients and
farm override have their own provenance, without a claim of FAO/local validation.

Further context: [FAO crop water needs](https://www.fao.org/4/S2022E/s2022e07.htm)
and [FAO irrigation water needs](https://www.fao.org/4/S2022E/s2022e08.htm).
The supplied daily rainfall fraction is a simplified caller assumption; this
module does not apply FAO's separate monthly effective-rain formula to daily data.
FAO reference coefficients may need climate, wetting, and local crop adjustments.

## Irrigation response

Top-level fields: `status` (`calculated`, `partial`, `unavailable`), `data_type`
(`estimate`), `calculated_at`, `period_days`, `period_start_date`, `period_end_date`,
`weather_provenance`, `kc`, `farm_assumptions`, `daily`, `summary`, `warnings`,
`assumptions`, and `units`. Unknown/unusable weather can leave period metadata
`null`. `weather_provenance.status` retains live/cached and includes original
retrieval, validity limit, original horizon, and assessment period.

Each daily record has `date`, `et0_mm`, `kc`, `etc_mm`,
`crop_water_consumption_liters`, `precipitation_mm`, `effective_rain_mm`,
`net_irrigation_mm`, `net_irrigation_liters`, `gross_irrigation_liters`,
`runtime_hours`, `status`, and `warnings`. Depths are mm/day, volumes liters,
runtime hours, Kc dimensionless. A missing flow makes runtime unavailable without
making otherwise supported supplied-water demand incomplete.

`summary` has `status`, `period_days`, `available_days`, `complete_days`,
`incomplete_days`, `total_etc_mm`, `total_crop_water_consumption_liters`,
`total_effective_rain_mm`, `total_net_irrigation_liters`,
`total_gross_irrigation_liters`, `total_runtime_hours`, and `partial_totals`.
`period_days` means requested days, not just returned rows. Complete days have a
gross estimate; absent dates also count as incomplete. Each full-period total is
`null` unless that metric is available for every requested date.

Each entry in `partial_totals` independently reports `value`, `dates`,
`covered_days`, `requested_days`, and `status` (`complete`, `partial`,
`unavailable`). This makes an available ETc total usable even when efficiency is
missing, without presenting a partial gross volume as weekly demand.

## Water budget response and period alignment

`calculate_water_budget(irrigation_result, water_available_liters)` accepts a
nonnegative finite numeric supply for the SAME requested upcoming period. A
scalar supply cannot establish dates or actual delivery capacity. Optional
`water_period_start_date` and `water_period_end_date` must be supplied together
and match the irrigation period exactly. Optional aware `reference_time` has the
same backend-only replay purpose as in the irrigation function.

For a complete fresh period:

```text
shortage_liters = max(required_gross_liters - available_liters, 0)
surplus_liters = max(available_liters - required_gross_liters, 0)
coverage_percentage = min(available_liters / required_gross_liters * 100, 100)
```

Zero known demand uses 100% coverage by explicit convention and performs no
division. This says nothing about crop safety. Surplus is only an arithmetic
excess, not a guarantee of storage or delivery.

The budget response has `status`, `period_days`, `period_start_date`,
`period_end_date`, `weather_provenance`, `water_required_liters`,
`water_available_liters`, `water_shortage_liters`, `water_surplus_liters`,
`coverage_percentage`, `water_status` (`sufficient`, `shortage`, `unavailable`),
`indicator`, `partial_assessment`, `warnings`, `assumptions`, and `units`.

Missing gross demand or date coverage leaves the main comparison metrics `null`
and `water_status: unavailable`; it does not label a farmer sufficient for a
week based on fewer days. If some gross volumes are known, `partial_assessment`
has scope `known_dates_only`, covered/requested days and dates, subset comparison
metrics, and a warning that the remaining demand is unknown. The same availability
is shared across the whole period; the subset surplus cannot be reused as another
independent allocation. Ignore this subset for any full-week sufficiency claim.

The budget rechecks forecast provenance, expiry, units, dates, daily coverage,
and consistency between a complete period total and daily gross volumes. Expired
data return unavailable even if they were valid when irrigation was calculated.

## Confirmed irrigation records

```python
summary = summarize_irrigation_records([
    {"id": "actual_001", "date": "2026-10-09", "applied_liters": 5000, "status": "confirmed"},
    {"id": "plan_001", "date": "2026-10-11", "applied_liters": 9000, "status": "planned"},
])
```

This hypothetical record summary counts only the 5000 confirmed liters. Planned
or proposed volumes are separately reported as unconfirmed. Valid ISO dates,
unique nonblank/unpadded IDs and nonnegative finite volumes are required for all
records, including planned ones. Supported statuses are confirmed/planned/proposed.
The response includes confirmed/unconfirmed IDs, counts and totals, and a warning.
It summarizes the provided list; caller controls its date scope and verifies the
truth of farmer confirmations. No database write, soil-water credit, or proof of
root-zone satisfaction is implied. Passing extra farm record metadata does not
change future irrigation demand.

## Executed examples, errors and limits

[irrigation_examples.json](irrigation_examples.json) contains exact executed
requests/responses for complete data, shortage, sufficient supply, missing
efficiency, missing ET0, cached partial coverage, expiry, runtime, the independent
one-day mathematical case, and confirmed records. Farm and record data are
hypothetical. The complete weather examples replay the genuinely captured
forecast at its original 2026-10-09 retrieval time; they are not current forecasts
on October 10. Missing-ET0 alteration and mathematical contract mocks have
explicit synthetic example labels. Do not load those mocks as production weather.

The historical complete example has 29.88 mm ET0, 34.362 mm ETc, 34,362 liters
crop/net consumption and 38,180 liters gross demand. With explicit 30,000-liter
availability, estimated shortage is 8,180 liters; with 50,000 liters, arithmetic
surplus is 11,820 liters. Runtime at 2000 liters/hour is 19.09 hours over that
period, not a continuous-run recommendation.

The synthetic independent one-day case declares its period explicitly: ET0 5,
Kc 1.15, area 1000, rainfall 0, efficiency 0.9, flow 2000. Executed results:
ETc 5.75 mm, net 5750 liters, gross 6388.888888888889 liters, runtime
3.1944444444444446 hours. Available 5000 liters produces shortage
1388.888888888889 liters and coverage 78.26086956521739%. UI display may round
these values; calculation results are not display-rounded.

Invalid farm/settings/supply/record inputs raise `ValueError` for Member 2 to map
to validation responses. Invalid or expired weather and inconsistent derived
budget inputs produce unavailable estimates with warnings. No missing financial
or water assumptions are silently invented.

Arithmetic uses an independent input-dependent Decimal context with at least 50
significant digits; recurring divisions have finite precision. Outputs use JSON
numbers for compatibility with weather. Conversion to floats imposes ordinary
JSON-number precision; the budget allows only small serialization differences
when checking a full total against daily volumes. Out-of-range/underflowed derived
numbers are rejected rather than serialized as Infinity or false zero. This is
not monetary accounting, and the Decimal-string Financial Module is unchanged.

The MVP does not model soil moisture/storage, salinity, groundwater, runoff or
drainage detail, changing Kc within a week, precise timing, field-calibrated
efficiency, disease, or crop-loss percentages. It does not recommend reducing
water below agronomic needs. Actual operation requires field confirmation.

Run the whole suite, including financial and weather regressions:

```text
python -B -m pytest -q -p no:cacheprovider
```

Calculation tests use mocked weather, plus an offline replay of the previously
captured genuine snapshot. No real API requests are made by these modules/tests.
