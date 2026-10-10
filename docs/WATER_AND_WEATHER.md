# Dated water allocations and weather fallback

## Storage and calculation policy

Water allocation belongs to CropSeason, which is linked to a plot and farm.
It is a total allocated volume for an explicit inclusive period, not tank
capacity or a daily allowance. The model currently stores one allocation per
season. It is not an allocation ledger and does not subtract recorded irrigation.

Additive Alembic revision `20261010_0003` adds:

- `water_available_liters`: nullable Numeric(16,3), nonnegative.
- `water_period_start`, `water_period_end`: nullable inclusive local dates.
- `water_allocation_is_demo`: a server-controlled provenance flag, false by default.

Existing rows remain unknown; the migration never backfills 4,000 liters.
Only creation of the canonical demo season by the seed command stores 4,000
liters, labeled as seeded demo, for the seeding date through six days later
(Asia/Amman). Rerunning the seed preserves existing values, including cleared
or expired allocations. Editing an allocation's amount or dates changes its
provenance to user-entered; clients cannot set the demo flag.

Supply amount and both dates together, or null all three to clear the allocation.
Reject negative/nonfinite amounts, precision beyond three decimal places,
reversed dates, and periods outside the declared season. Zero means explicitly
no available water; null means unknown.

The allocation dates must match the irrigation forecast dates exactly. A stale,
longer, shorter or absent period cannot establish full-period sufficiency.
Dashboard `water_available_liters`, shortage, surplus and coverage stay null
when the amount is unknown or mismatched. Saved amount/dates remain visible as
`allocation_liters`, `water_period_start`, `water_period_end`; the forecast dates
are returned separately. Known demand remains available. `status=missing_data`
and `missing_inputs` explain why a comparison cannot be made.

Forecasts move forward every day. Allocations do not roll forward or prorate
automatically: users must enter a matching allocation for the new horizon.
This conservative policy avoids treating a multi-day total as wholly available
to every overlapping forecast. No yield response is modeled.

## API and UI

- Canonical farm POST/GET includes the three water fields for the active season.
- UI season GET/POST/PATCH exposes and updates the same stored fields.
- Example PATCH `/api/ui/farms/{farm_id}/seasons/{season_id}`:

```json
{
  "water_available_liters": 2500,
  "water_period_start": "2026-10-10",
  "water_period_end": "2026-10-16"
}
```

Use the actual forecast dates, not these illustrative dates. The management
dialog has Arabic and English amount/start/end inputs. Optional empty dates
stay empty. The irrigation card shows available water, allocation dates and
the seeded-demo label, or explicitly says that availability is unknown.

Simulation overrides remain non-persistent and apply to the forecast period.
Zero is a valid override. If no water override is provided, the simulator uses
the same saved-period validation as the dashboard, including unknown values.
Simulation may refresh the weather cache but does not write allocation records.

## Weather provenance and completeness

Provenance (live/cached) and coverage (complete/partial/unavailable) are separate.
Canonical weather returns `data_kind=null` when no usable forecast exists:
unavailable data is not described as cached. Canonical status mapping is:

| Forecast | status | data_kind | coverage_status |
|---|---|---|---|
| Complete live | ok | live | complete |
| Complete cache | estimated | cached | complete |
| Partial live/cache | missing_data | live/cached | partial |
| Unavailable | unavailable | null | unavailable |

The UI weather route retains `status=live/cached/unavailable` for compatibility
and adds coverage_status, coverage, missing_inputs and errors. Coverage contains
requested/available/complete day counts, per-field counts and hourly humidity
coverage. The dashboard displays completeness, missing fields, source and original
retrieval timestamp independently. Cached data retains its original timestamp;
it is not relabeled as a new live observation.

## Cache isolation and persistence

Application weather calls always enable validated snapshot saving and use a
SHA-256 path derived from farm ID and its stored latitude/longitude (six decimal
places). Farm IDs cannot become file paths. Separate farms, even at the same
coordinates, have different files; changing either coordinate selects another
file. The weather service additionally validates saved coordinates and provenance.

`WEATHER_CACHE_DIR` defaults to `data/weather-cache`. Docker Compose overrides
it to `/app/weather-cache` and mounts a dedicated named volume. The directory
must be writable by the API process. Runtime snapshots are excluded from Git
and the Docker build context. The old WEATHER_SNAPSHOT_PATH setting/shared sample
file is not used by application routes; caches begin empty until a valid live
retrieval is saved. No synthetic snapshot is installed automatically.

The existing weather service atomically saves only complete validated live
forecasts. Partial/malformed responses do not replace a good snapshot. A valid
partial live response is exposed as partial; it is not silently replaced by
older complete data. On live retrieval/validation failure, fallback uses only
fresh validated cached data (24-hour default maximum age). Past days are removed,
so a still-fresh cache can have partial coverage. Write failures produce warnings
without discarding valid live results. There is no scheduled refresher, cleanup
job or cross-worker request deduplication; old coordinate-keyed files can remain
on disk, but only the matching fresh file is eligible for use.

## Applying and verifying

Apply `alembic upgrade head` in your intended deployment environment before
starting the updated API. This task applied migrations only to a disposable
SQLite database. It did not modify an existing real database or call external
weather/AI services.

Focused tests:

```powershell
$env:DATABASE_URL = 'sqlite+pysqlite:///:memory:'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest -q -p no:cacheprovider tests/test_water_weather_persistence.py tests/test_weather.py
node --test tests/frontend.test.cjs
```

Use a fresh writable --basetemp directory if required by the local sandbox.
Tests cover additive migration/data preservation, seeded-only demo defaults,
database connection restart, unknown versus zero water, strict period validation,
simulation isolation, partial/cached/stale weather, rejected snapshot overwrites,
write failures, multiple farms/coordinates and frontend data propagation.

PostgreSQL migration execution, live providers, Docker volume behavior and visual
browser layout remain unverified in this environment. Automated frontend checks
exercise data handling and JavaScript syntax, not a full browser session.
