# `/api/ui` contract

Verified against the implementation on 2026-10-10. Interactive request schemas are at `/docs`; canonical APIs remain available. This is a local single-owner demonstration, not an authenticated tenancy API.

## Common rules

JSON request bodies reject unknown fields and non-finite numbers. Dates are ISO `YYYY-MM-DD`, interpreted in Asia/Amman for activity timestamps. Activity dates must be on/after the associated season start, including PATCH and season moves. Moving a season start may not invalidate existing records. HTTP 422 is invalid input, 404 is unknown/unowned resource, 409 is conflicting state/key, and 503 indicates an unavailable optional provider. DELETE returns 204 when successful.

POST creates support `Idempotency-Key` (1–150 characters) for farms, seasons and records. Scope is the corresponding farm/collection (farm creation uses owner scope). Identical normalized retries return the original saved response with 201, including after edits to the record; a changed payload under the same key returns 409. Database transaction/unique constraints arbitrate concurrent submissions. Keys are optional for compatibility; without a key separate POSTs are separate writes. Reuse the key/payload after an uncertain response, and generate a new key for a new intentional operation. The browser retains uncertain keys in memory; reload/browser-close does not provide durable offline retry storage. PATCH/DELETE are not receipt-backed creates.

Money is stored to 3 decimal places (JOD), prices to 4 (JOD/kg), most recorded quantities to 3. Excess monetary precision is rejected rather than silently rounded. Unknown inputs/results are null or explicit missing metadata, never synthetic zero. A true entered zero is distinct from unknown. `origin` is `api` or explicitly seeded `sample`; assistant adds `fallback`.

## Farm and season endpoints

| Method/path | Contract |
| --- | --- |
| GET `/farms` | `{farms:[...]}` owner farm summaries |
| POST `/farms` | Creates farm, plot and initial season; returns farm summary |
| GET/PATCH/DELETE `/farms/{id}` | Retrieve, merge validated profile fields, or delete |
| GET `/farms/{id}/seasons` | `{origin,seasons:[...]}` |
| POST `/farms/{id}/seasons` | Create named tomato season |
| PATCH/DELETE `/farms/{id}/seasons/{season_id}` | Validate merged season or delete subject to existing state constraints |

Farm create requires name, location, latitude, longitude, positive area_dunum (1 dunum = 1,000 m²), planting_date and crop_stage (`initial`, `development`, `mid_season`, `late_season`). Only tomato/drip is supported. Optional establishment_method, irrigation_efficiency, effective_rain_fraction and system_flow_liters_per_hour preserve missing values.

Season fields: name, start_date, optional end_date, is_active, expected_harvest_kg (remaining marketable quantity), projected_costs_jod (remaining costs), fertilizer_budget_jod, assumed_sale_price_jod_per_kg. Water fields are water_available_liters, water_period_start, water_period_end: set a complete valid triple or clear all to null. Allocation must be finite/nonnegative and its period must fit the season; see WATER_AND_WEATHER.md for exact checks. No universal allocation is assumed.

## Records

GET/POST `/farms/{id}/{expenses|irrigation|harvests|sales}` and PATCH/DELETE `/farms/{id}/{collection}/{record_id}`. Common create fields: date, optional season_id (defaults to active season).

| Collection | Required values / list response |
| --- | --- |
| expenses | category, nonnegative amount_jod; optional description. List `{origin,expenses}` |
| irrigation | confirmed=true; positive volume_m3 or amount_mm. If both provided they must agree for plot area. Converted storage minimum 0.001 L. List `{origin,records,estimate,water_budget}` |
| harvests | positive quantity_kg; optional grade/notes. List `{origin,harvests}` |
| sales | positive quantity_kg, nonnegative unit_price_jod; optional same-season harvest_id, buyer, notes. List `{origin,sales}` |

`POST /farms/{id}/costs` is a compatibility alias for expense creation. Lists include farm records across seasons; financials use the active season. Sale/harvest references must belong to that season.

## Read/calculation endpoints

- GET `/farms/{id}/financials`: authoritative recorded/projected costs, revenue, profit, per-kg/break-even values, actual sold/harvest quantities, expected remaining harvest, warnings and provenance. Full-season cost/kg and average break-even use sold + remaining marketable quantity. They are not future-only break-even prices.
- GET `/farms/{id}/weather`: source, fetched_at, status (`live`, `cached`, `unavailable`), coverage_status, coverage, missing_inputs, warnings/errors and daily fields. Live status alone does not mean complete coverage.
- GET `/farms/{id}/recommendations`: bilingual summary/action/why, typed metric evidence with units, sources, limitations, generated from actual calculator results and farm records.
- GET `/farms/{id}/inspections`: advisory reminders, assessment and limitations, not diagnoses.
- GET `/farms/{id}/fertilizers`: dated supplier catalog and explicit availability/price limitations, not pesticide advice.

POST `/farms/{id}/simulate` accepts `{"overrides":{"water_available_liters":0}}`. At least one finite nonnegative override is required. Other keys: expected_marketable_kg, sale_price_jod_per_kg, additional_costs_jod. Response: farm_id, generated_at, persisted=false, baseline `{water_budget,finance}`, scenario water_budget/finance, unsupported_effects. Baseline and scenario use the same forecast context. No farm/season/ledger write occurs; weather cache may refresh. Shortage does not change predicted yield.

## Assistant and voice

POST `/assistant/chat`: `{farm_id,message,language:"ar"|"en"}` → `{answer,sources:[{title,url}],origin,limitations}`. Trimmed nonempty message maximum 2,000 characters. Relevant local bilingual retrieval is cited; no relevant passage is explicitly disclosed. Groq chooses only validated structured references; deterministic rendering enforces metric/unit relationships. Provider failure/invalid output returns useful bilingual fallback. The assistant cannot write farm records.

POST `/assistant/voice`: `{farm_id,recommendation_id,language:"ar-JO",voice_id:"ar-JO-TaimNeural"}` → `{audio_url,text,voice_id,demo_mode:false}` only after accepting provider audio. Missing provider configuration/failure returns 503; unknown recommendation returns 404. GET returned audio_url yields audio/mpeg; in-memory audio expires after 10 minutes and cache is bounded. Credentials never reach the browser. Browser speech is separately labeled and requires an Arabic voice. Header validation catches obvious malformed provider content but is not a complete MP3 decoder.
