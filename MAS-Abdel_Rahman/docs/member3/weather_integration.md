# Member 3 weather integration

Python 3.10+, standard library only. This module retrieves Open-Meteo model
forecasts for caller-supplied farm coordinates, normalizes daily weather, and
provides dashboard summaries and inspection reminders. It has no database,
FastAPI, frontend, irrigation scheduling, or disease-diagnosis dependencies.
The Financial Module is unchanged.

## Member 2 entry point

```python
from backend.services.weather import get_weather

result = get_weather(32.19, 35.62)
```

The example coordinates are a Jordan Valley demonstration point, not a verified
farmer's location. The engine has no hardcoded farm coordinates. Latitude and
longitude accept finite Python int/float values, excluding booleans and strings,
in [-90, 90] and [-180, 180]. Invalid caller inputs raise `ValueError` before HTTP;
Member 2 may map this to HTTP 422.

Existing two-argument callers need no changes. Optional keyword arguments:

| Setting | Default | Meaning |
| --- | --- | --- |
| `timeout_seconds` | 10 | One request, no retries; must be >0 and <=60 |
| `snapshot_path` | Repository `data/sample_weather.json` | Fallback file; `None` disables fallback |
| `cache_max_age_hours` | 24 | Nonnegative maximum snapshot age, <=168 hours |
| `save_snapshot` | `False` | Opt-in atomic saving of a complete, consistent live retrieval |
| `rain_threshold_mm` | 5 | Nonnegative daily precipitation reminder threshold |
| `heat_threshold_c` | 35 | Finite daily maximum temperature reminder threshold |
| `wind_threshold_kmh` | 30 | Nonnegative daily maximum wind reminder threshold |

The HTTP call is synchronous; use the backend's existing sync/threadpool pattern
when integrating with async FastAPI handlers. Do not rewrite engine internals or
add financial/weather formulas to routes. Call with farmer coordinates and handle
the returned status. For multiple farms, configure a separate server-owned
snapshot path per farm. There is no automatic polling, in-memory cache, or worker.

## Provider request

The adapter uses the [official Open-Meteo Forecast API](https://open-meteo.com/en/docs),
`https://api.open-meteo.com/v1/forecast`, with these parameters:

```text
latitude=<caller value>
longitude=<caller value>
daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,et0_fao_evapotranspiration,weather_code
hourly=relative_humidity_2m
timezone=Asia/Amman
forecast_days=7
temperature_unit=celsius
wind_speed_unit=kmh
precipitation_unit=mm
timeformat=iso8601
```

No API key or additional runtime package was added. Maintain provider attribution
in the UI. Returned provider coordinates can refer to a model grid cell; requested
farm coordinates and provider coordinates are reported separately.

## Normalized response

All keys use snake_case. Weather values are JSON numbers, not financial Decimal
strings. Unknown values are `null`, not zero. [weather_example.json](weather_example.json)
is the complete exact normalized response from the real smoke test. The original
timestamped provider response is in [sample_weather.json](../../data/sample_weather.json).

Top-level fields:

| Field | Meaning |
| --- | --- |
| `status` | `live`, `cached`, or `unavailable` |
| `source`, `data_type` | `open-meteo`, `forecast`; these are never observations |
| `retrieved_at` | Actual original UTC retrieval timestamp; `null` if unavailable |
| `timezone` | `Asia/Amman` |
| `latitude`, `longitude` | Requested coordinates |
| `provider_latitude`, `provider_longitude` | Returned model grid coordinates, or `null` |
| `forecast_start_date`, `forecast_end_date` | Current requested local seven-day period, or `null` |
| `daily` | Only available valid dates in that period; no invented missing days |
| `summary`, `advisories`, `warnings` | Structured dashboard/AI context |
| `units` | Explicit unit metadata |
| `errors` | Error objects with `type` and `message`; includes failed live retrieval when using cache |

`live` means a fresh API retrieval, not necessarily complete data. Check
`summary.status` and field coverage. `cached` means live retrieval failed and a
validated snapshot was used; keep the original timestamp visible. `unavailable`
returns empty daily/advisory lists, unavailable summary metrics, `retrieved_at:
null`, and error explanations. Do not treat this as dry weather or zero ET0.

Each daily record contains:

| Key | Unit / interpretation |
| --- | --- |
| `date` | Local ISO YYYY-MM-DD |
| `temperature_max_c`, `temperature_min_c` | Degrees Celsius |
| `precipitation_mm` | Daily precipitation amount, mm |
| `rain_probability_max_percent` | Maximum daily forecast precipitation probability, 0-100%; never a rainfall amount |
| `relative_humidity_mean_percent` | Mean of available valid hourly humidity percentages for that local date |
| `relative_humidity_hours_available`, `relative_humidity_hours_expected` | Valid unique hourly samples / 24 expected samples |
| `wind_speed_max_kmh` | Daily maximum 10-metre wind speed, km/h |
| `et0_mm` | FAO reference evapotranspiration, mm/day |
| `weather_code` | Provider WMO integer code; unknown codes are retained without invented labels |

Daily humidity uses the returned local timestamps, not UTC date slicing. Missing,
invalid, or duplicate hourly samples do not count toward coverage. A mean from
fewer than 24 samples is available but explicitly partial. If all samples are
missing, the mean is `null`. Today includes the provider's entire local calendar
day; hourly values are model data, not independently measured field observations.

Malformed numeric values become `null` with warnings. Costs are not calculated.
Nonnegative precipitation, wind, ET0 and 0-100 probabilities/humidity are enforced;
negative Celsius temperatures remain valid. Inverted temperature extrema are
withheld. Missing/short arrays are reported, and unmatched trailing data are not
used. Wrong daily units, missing usable daily dates, and unexpected timezone
metadata reject the provider response and allow fallback. Missing humidity only
makes the response partial.

## Seven-day summary and reminders

`summary.status` is `complete`, `partial`, or `unavailable`. The summary includes
`requested_days`, `available_days`, `total_precipitation_mm`, `total_et0_mm`,
`heat_days`, `wind_days`, `rainy_days`, `metric_status`,
`available_days_per_metric`, `available_days_per_field`, `humidity_hours_available`,
`humidity_hours_expected`, and `thresholds`.

Totals/counts represent the available subset when `metric_status` is `partial`;
the coverage is reported alongside them. They are `null` if no relevant values
exist or a numeric aggregate overflows. Missing values never silently contribute
zero to a supposedly complete aggregate. Rainy days have precipitation >0 mm.
Heat/wind counts use the same strict > comparisons as reminders. Overall
completeness also requires all requested daily fields and 168 valid humidity hours.

Each advisory has `date`, `type`, `metric`, `value`, `threshold`, and `message`:

| Type | Demonstration trigger | Reminder |
| --- | --- | --- |
| `rain_irrigation_review` | Precipitation >5 mm/day | Review irrigation schedule and check actual soil moisture |
| `heat_inspection` | Maximum temperature >35 C | Inspect tomato plants and verify soil moisture |
| `wind_inspection` | Maximum wind >30 km/h | Inspect exposed plants and field conditions |

Threshold equality does not trigger an advisory. Missing required values do not
trigger advisories. These configurable defaults are demonstration heuristics,
not scientifically validated tomato risk thresholds. They do not cancel
irrigation, diagnose disease, predict crop loss, or guarantee plant protection.

Independent helpers for normalized data are `summarize_weather(daily, ...)` and
`generate_weather_advisories(daily, ...)`. `normalize_weather_response(...)`
validates provider-format payloads; `aggregate_daily_humidity(...)` groups valid
local hourly humidity. Normalization can take an aware `reference_time` for
deterministic offline checks. Helper inputs must follow their documented formats.

## Saved-response fallback

The engine attempts live HTTP first. Only after retrieval/critical validation
failure does it read a trusted server-owned snapshot. Snapshot schema is
`snapshot_version: 1`, `source: open-meteo`, `data_type: forecast`, original
`retrieved_at`, requested `latitude`/`longitude`, `request_url`, and `api_response`.
Source labels cannot authenticate manually fabricated data; do not load snapshot
files supplied by untrusted clients. Synthetic fixtures exist only in mocked tests.

Snapshot coordinates must match the requested farm within 0.000001 degree per
axis. Retrieval age must be within the configured limit and cannot be future-dated.
Dates must belong to the original retrieval's seven-day period. Normalization
then excludes every date before today's Amman date or after today's requested
window, recomputes summaries/advisories using current thresholds, and labels
remaining coverage partial where appropriate. A cache cannot restore the next
day beyond its original horizon. Expired snapshots return unavailable; they are
not supplied as current forecasts or historical substitute irrigation data.

By default no files are written. `save_snapshot=True` saves only a complete live
response with consistent raw arrays via a temporary file and atomic replacement.
Partial/malformed results and saving failures preserve the previous snapshot.
Saving failure is a warning and does not hide usable live data. The default sample
file is a genuine demonstration snapshot, not a durable offline weather service;
it will expire. Provision fresh per-farm snapshots explicitly when needed.

The implementation uses Asia/Amman's current UTC+03:00 offset for local date
boundaries and checks the provider's matching offset. If Jordan changes timezone
rules, that check rejects the response until Member 3 updates the offset. No
external timezone-data dependency is required.

## Actual smoke test and downstream use

One live request at demonstration coordinates 32.19, 35.62 succeeded at
**2026-10-09T20:54:24.642303Z**. It returned seven daily dates (October 9-15),
all seven requested daily variables, and 168 hourly humidity values. The normalized
summary was complete: 0 mm forecast precipitation, 29.88 mm reference ET0,
2 days above the 35 C heat threshold, and 0 days above the wind threshold.
These describe that captured forecast, not a claim that it remains current.

Member 1 can display `daily`, `summary`, `advisories`, and `warnings` directly,
including status/coverage and cached retrieval age. Member 2 passes coordinates,
checks status/errors, and forwards this JSON-compatible result. No internal
Weather Engine changes are required for integration.

The future Irrigation Engine may consume each day's finite `et0_mm` and
`precipitation_mm` with date, freshness, source, and coverage checks. ET0 is
reference evapotranspiration, not tomato-specific demand or irrigation litres.
Later ETc = ET0 x stage-dependent Kc; crop coefficients, effective rainfall,
soil moisture, farm area, and system efficiency belong in that separate engine.
Rain probability must not be substituted for precipitation quantity. A missing
ET0/rainfall field needs an explicit downstream unavailable-data policy.

Error types are `http_error`, `timeout`, `network_error`, `invalid_response`,
and `cache_unusable`. Optional-field issues appear in warnings. Requests have
no retries. Numerical weather/model uncertainty and actual field conditions are
not estimated by this adapter.

Run the entire suite from the repository root:

```text
python -B -m pytest -q -p no:cacheprovider
```

Weather unit tests mock HTTP and cannot contact the live API. Separate offline
tests reproduce the exact real example from the saved raw response and verify
that it cannot be used after expiry. The Financial Module's existing regression
tests remain part of the full suite.
