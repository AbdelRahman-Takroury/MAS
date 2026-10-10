# Smart Farm AI backend

The frontend remains the existing static HTML/CSS/Vanilla JavaScript app. This FastAPI service implements its `/api` contract and persists farm records with SQLAlchemy. Local development uses SQLite by default; PostgreSQL is available through the optional root `docker-compose.yml`.

## Local development (SQLite, no Docker required)

From the project root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In a second terminal, serve the existing frontend:

```powershell
python -m http.server 5500 --bind 127.0.0.1
```

Open `http://127.0.0.1:5500/dashboard.html?api=http%3A%2F%2F127.0.0.1%3A8000%2Fapi` to use the backend. Open `http://127.0.0.1:5500/dashboard.html` without the `api` query parameter to keep using the existing labeled frontend mock data. If the frontend is served from another origin, add it to `CORS_ORIGINS` (comma-separated origins) before starting the API.

For local provider configuration, copy `.env.example` to `.env`. The API reads that file on startup. Groq chat and Azure Arabic speech are optional; use credentials issued for those services. Never add real credentials to JavaScript or commit `.env`.

The default database is `backend/data/smart_farm.db`. SQLAlchemy creates missing tables on API startup; rows remain in this file across server and browser restarts. `GET /api/health` is the health check and `/docs` on port 8000 is the interactive API reference.

## Seed profiles

Seed the three existing sample farm **profiles** into an empty database:

```powershell
python -m backend.app.seed
```

The seed command does not overwrite a database containing farms. Seeded farms carry `origin: "sample"`, so the dashboard labels them as sample data. It seeds no invented irrigation, weather, inspection, expense, harvest, or sales records.

## PostgreSQL with Docker Compose

Docker Compose is optional. Copy `.env.example` to `.env`, replace the local database password, then run:

```powershell
Copy-Item .env.example .env
# Edit .env and replace POSTGRES_PASSWORD with a local password.
docker compose up --build -d
docker compose exec api python -m backend.app.seed
```

Open `http://localhost:5500/dashboard.html?api=http%3A%2F%2Flocalhost%3A8000%2Fapi`. PostgreSQL data is held in the named volume `smart_farm_pgdata`.

To reset a local SQLite database, stop the API and back up `backend/data/smart_farm.db` before removing it; the next API start recreates an empty schema. To reset PostgreSQL, `docker compose down -v` removes the database volume and all persisted records; use it only when that data is intentionally disposable.

## API routes

All application routes use `/api`:

- Farms: `GET/POST /farms`, `GET/PUT/PATCH/DELETE /farms/{farm_id}`.
- Growing seasons: collection CRUD at `/farms/{farm_id}/seasons` and `/seasons/{season_id}`.
- Irrigation, expenses, harvests, and sales: collection CRUD at `/farms/{farm_id}/{resource}` and `/.../{record_id}`.
- Existing frontend compatibility: `GET /farms/{farm_id}/irrigation`, `POST /farms/{farm_id}/irrigation`, `POST /farms/{farm_id}/costs`, and `GET /farms/{farm_id}/financials`.
- Fertilizer comparison: `GET /farms/{farm_id}/fertilizers` returns dated supplier listings and compares one package with the active season's saved fertilizer budget when present. Details and provenance are in [`fertilizer-catalog.md`](fertilizer-catalog.md).
- `GET /farms/{farm_id}/weather` uses the team's Open-Meteo adapter and validated cached snapshot when farm coordinates exist. It returns explicit status/missing coordinates, preserves unknown weather codes and missing daily values, and reports provider timestamp/errors. Sample coordinates remain demo-only.
- `GET /farms/{farm_id}/irrigation` returns a structured status even when an estimate cannot be calculated. It only runs for drip farms with a supported tomato stage, positive area, and usable forecast; it passes through the farm's actual method and refuses unsupported methods. Values are total liters across the forecast period; partial totals are separately scoped to covered dates. Runtime remains unavailable unless measured system flow is known.
- Dashboard stage labels are mapped to the engine's tomato stages with a visible note in the returned estimate/report. The development-stage coefficient is an estimate, not a locally calibrated value.
- Inspection reminders are weather-threshold field checks only; they are not disease diagnoses. The recommendation endpoint provides a data-completeness reminder when inputs are missing and no agronomic advice when they are not.
- Financial summaries continue to use persisted records. The team's financial engine now calculates actual cost per sold kg and actual break-even price only when recorded costs and sold quantities support them. Fertilizer listings are served by `GET /farms/{farm_id}/fertilizers` as a dated supplier-price snapshot; one-pack budget comparison uses only the active season's recorded fertilizer budget.
- `POST /assistant/chat` can call Groq if `GROQ_API_KEY` is configured in the server environment. Without it, it returns a bilingual fallback. Groq was not live-tested here, and no knowledge-base/source citations are currently wired in.
- Arabic voice uses Azure Speech through the existing voice contract. Missing credentials return HTTP 503; actual synthesis requires valid `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` and was not live-tested here.

Create requests for irrigation, expenses, harvests, and sales accept `Idempotency-Key`. Reusing the key with the same body returns the existing record; reusing it with a different body returns HTTP 409. The frontend also coalesces identical simultaneous writes. All endpoints validate input and return 404 for missing farm/record IDs and 422 for invalid fields or cross-farm season references.

Financial totals are calculated from persisted expenses, harvests, sales, and active-season projections. `expected_harvest_kg` is a farmer-entered active-season value, not a forecast; actual harvest is the sum of recorded harvest entries and is labeled as all-seasons scope, with a separate active-season sum when harvest entries reference that season. The API does not infer biological yield. The fertilizer catalog is separate from financial totals and does not create expenses or infer a fertilizer plan. It includes source links, package price, normalized JOD/kg, listed product profile, and an optional arithmetic comparison to the active-season budget. Prices are retail listings checked on the stated date and must be confirmed with the supplier. No dose or agronomic recommendation is inferred.

## Tests

```powershell
python -m pytest backend\tests -q
```

The root backend and team engine suites use mocked providers for deterministic coverage. During the October 10, 2026 verification, a separate request to the configured local backend fetched seven live forecast days from Open-Meteo for the seeded sample farm (`origin: sample`, provider: `open-meteo`). This confirms connectivity and response parsing at that time only; it does not validate the sample coordinates or establish service availability later. Groq, Azure Speech, and PostgreSQL were not live-tested.

Irrigation amounts are planning estimates, not field-validated schedules. The model converts ET0 to crop demand using stage Kc, subtracts assumed effective rainfall, applies the configured irrigation efficiency, and multiplies millimeter depth by square-meter area to obtain liters. Its fixed/interpolated coefficients and the farm's efficiency/rain assumptions require local agronomic and equipment verification; the result omits soil moisture/storage, root depth, groundwater, runoff, salinity, drainage, and previous irrigation. Do not treat it as accurate field advice until calibrated against measured soil and water observations.

## Schema initialization and upgrades

`Base.metadata.create_all()` initializes a new database automatically. Startup also adds the nullable farm coordinates and irrigation-assumption columns if they are absent and applies the documented Jordan Valley demonstration values only to matching sample farms. This is a targeted compatibility upgrade, not a general migration system; use Alembic for future schema changes. Back up the database before any reset or migration.

The backend imports the team's original calculation/provider modules from `MAS-Abdel_Rahman/backend`; the Docker image includes that folder. Keep it alongside the root `backend/` directory. The weather provider needs outbound access to Open-Meteo, but no API key. Put Groq and Azure Speech credentials in root `.env` only; never put them in browser JavaScript or commit `.env`.
