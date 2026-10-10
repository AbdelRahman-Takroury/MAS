# Integration readiness and planning handoff

Reviewed on 2026-10-10 (Asia/Amman). Scope: local `Abdel_Rahman` working tree,
including uncommitted implementation of Steps 6–10. Committed HEAD is
`ca7a641` (persistence API). Governing plan: `member2_implementation_plan.txt`.

## Readiness verdict

Ready to plan Step 11, with the issues below resolved before freezing the
frontend contract. This is not a clean-checkout or live deployment sign-off.
The review created this handoff only; application behavior and the configured
`openai/gpt-oss-20b` model were preserved.

- Full local suite: **659 passed**, one Starlette TestClient deprecation warning.
- OpenAPI registers all nine application operations and both health endpoints.
- Persistence API tests use SQLite; Groq tests use mocks.
- Docker was absent from PATH and the usual Docker Desktop CLI location in this
  environment. PostgreSQL restart persistence, container startup, and live service
  readiness were not verified in this review.
- No frontend implementation was found in this workspace; Member 1 compatibility
  and browser behavior remain unverified.
- Steps 6–10 have untracked files and tracked modifications. A checkout of HEAD
  alone does not contain the working dashboard, simulator, RAG, or assistant.

## Issues to resolve before contract freeze

| Priority | Finding and evidence | Required outcome |
| --- | --- | --- |
| High | `services/dashboard.py::_finance_module` only sends a future sale when both quantity and price exist. A probe with 100 JOD cost, 2000 kg and unknown price returned null break-even. | Preserve the calculable 0.05 JOD/kg break-even while withholding revenue/profit; reuse Salah's `prepare_financials` missing-price path. |
| High | `services/assistant.py::_numbers_are_grounded` accepts `Apply 999999L` with a fixture that contains no such value. Its regex skips numbers next to word characters. Even recognized numbers are checked by membership, not by metric/unit meaning. | Strengthen grounding and add adversarial response tests before relying on this check. |
| High | Assistant language, diagnosis, pesticide and yield-loss restrictions are prompt instructions, not verified output guarantees. The current acceptance checks only inspect numbers and presence of a title. | Test those requirements; use validated output or deterministic responses when model output cannot meet them. Earlier claims that the prompt *prevents* these outputs were too strong. |
| Medium | `services/dashboard.py::_weather_module` returns `ok` for cached and partial live responses; `contracts/README.md` specifies cached → `estimated`. | Align statuses and missing-input metadata with provenance and coverage; preserve retrieval timestamps. |
| Medium | `services/inspection.py` checks only supplied rows. A cached forecast with one populated day and seven requested days returned `not_favorable`. | Define coverage requirements and distinguish incomplete periods from fully assessed no-alert periods. |
| Medium | `AssistantRequest` accepts whitespace-only questions, then `retrieve_passages` raises an uncaught ValueError. | Reject blank-after-trimming input as HTTP 422. |
| Medium | Step 8 says to reject zero/negative harvest when requesting per-kg results. Current schema/tests accept zero and return null break-even; there is no per-kg request selector. | Agree on one interpretation and align plan, API validation, fixtures and frontend behavior. Negative overrides are already rejected. |
| Medium | Expense and irrigation replay handling reads before insertion; concurrent same-key requests can hit a unique constraint without recovery. PostgreSQL Numeric rounding can also make a >3-decimal expense replay differ from its stored value. | Define supported precision, validate or normalize input, and test concurrent idempotency on PostgreSQL. |

## Handoff contract available now

Defaults from Compose and `.env.example` (actual deployed values must be checked):

- API base: `http://localhost:8001`; Swagger: `/docs`; OpenAPI: `/openapi.json`.
- Allowed frontend origin: `http://localhost:5173` (exact origin; 127.0.0.1 differs).
- Sample farm: `demo_farm_001`; plot: `demo_plot_001`; season: `demo_season_001`.
- Demo owner: `demo_user_001`; there is no production login/authentication flow.
- Use `crop_season_id` returned by farm GET for expense and irrigation creation.
- Keep `GROQ_MODEL=openai/gpt-oss-20b`; key stays server-side. Empty key uses fallback.

| Method | Route | Response / use |
| --- | --- | --- |
| POST | `/api/farms` | 201 FarmResponse; creates farm, plot and active tomato season |
| GET | `/api/farms/{farm_id}` | 200 FarmResponse including plot/season IDs |
| POST | `/api/expenses` | 201 ExpenseResponse; also 201 on identical replay |
| GET | `/api/farms/{farm_id}/expenses` | 200 array; farm-wide records across seasons |
| POST | `/api/irrigations` | 201 IrrigationResponse; confirmed actions only |
| GET | `/api/farms/{farm_id}/irrigations` | 200 array; farm-wide records across seasons |
| GET | `/api/farms/{farm_id}/dashboard` | 200 weather, irrigation, water_budget, finance, inspection, actions |
| POST | `/api/farms/{farm_id}/simulate` | 200 SimulationResponse; nested `overrides` request; `persisted: false` |
| POST | `/api/assistant` | 200 answer, language, used_fallback, calculator/document references, limitations |

The assistant request contains `farm_id`, `language` (`ar` or `en`), and `question`.
`conversation_id` is accepted but currently unused; there is no conversation storage.
The simulator accepts water availability, expected marketable kg, price per kg,
and additional JOD costs. Null/omitted overrides retain the baseline value.

Frontend handling:

- Render null as unavailable, never as zero. Show status separately from data_kind.
- Show `is_sample`, warnings, assumptions, missing_inputs and source timestamps.
- Activities require offset-aware dates on/after crop establishment (2026-09-01
  for the sample). Units are encoded in field names; unknown fields are rejected.
- Reuse the same idempotency key when retrying an identical write. Same key with
  different data returns 409. Unknown/not-owned resources return 404.
- Domain errors have `{"detail": "message"}`. Validation errors have a `detail`
  array with field locations/messages. No shared custom error envelope exists yet.
- `/health/ready` checks the DB and returns 503 when unavailable; `/health/live`
  only confirms the API process is responding.

## Assumptions and decisions for the integration meeting

1. Water availability is always a labeled 4000-liter dashboard assumption, including
   non-sample farms. Only simulations can override it. Decide whether the demo
   exclusively uses the seeded farm or requires a persistent allocation field.
2. Seeded finance uses 2000 kg and 0.6 JOD/kg, but seeds no expenses. A newly created
   farm has unknown harvest/price, and the farm API has no fields to save them.
   Decide whether onboarding needs persistent finance inputs.
3. Finance aggregates both `cash` and `full` expense rows. Define whether these are
   additive entries or alternative views before Member 1 exposes that choice.
4. Module messages/actions are mostly English; the assistant supports Arabic prose.
   Decide which UI labels and server messages need translation for the Arabic demo.
5. Retrieval status `reviewed` describes the curated dataset; it is not evidence
   of local agronomist approval. Knowledge source limitations must remain visible.
6. No-match retrieval returns a zero-score general passage. The assistant currently
   treats that like ordinary context; decide how to communicate lack of relevance.

## Missing handoff artifacts

Existing fixtures cover farm creation, complete/missing dashboard, simulation
request and assistant response. Add fixtures for farm GET, expense/irrigation
requests and responses, simulation response, cached/partial weather, assistant
fallback and 404/409/422 errors. Current dashboard numbers are illustrative and
not an exact seeded-engine replay. Generate checked examples from deterministic
inputs and validate both schema and semantics.

README currently contains only the project title. Before sharing a runnable
handoff, document setup, migration/seed, endpoint examples, exact CORS origin,
test commands and limitations. The seed is idempotent creation, not a reset:
rerunning it preserves existing expenses and irrigation events.

## Proposed integration sequence and acceptance gates

1. Fix and regression-test the contract blockers above; record decisions on zero
   harvest, persistent financial inputs, water allocation and expense cost views.
2. Prepare the missing fixtures and startup documentation. Review all local
   changes and commit the intended files so another checkout contains Steps 6–10.
   Preserve/exclude the unused empty `knowladge` placeholders deliberately.
3. Verify from a clean environment, after creating `.env` from the example only
   when it does not already exist:

   ```powershell
   docker compose up --build -d
   docker compose exec api alembic upgrade head
   docker compose exec api python -m backend.app.seed
   docker compose exec api pytest -q
   ```

   Confirm `/health/live`, `/health/ready`, `/docs`, allowed-origin preflight,
   seeded farm retrieval and a persisted expense after container restart.
   These commands are proposed verification, not operations performed by this review.

4. Member 1 integrates in plan order: farm GET → dashboard GET → expense POST
   and refresh → simulate POST and unchanged refresh → assistant POST.
5. Run the complete journey twice with the actual frontend. Include Arabic and
   English assistant responses, missing key, provider timeout, current cached
   weather, missing weather, unknown harvest and idempotent retries.

The checked-in weather snapshot was retrieved at 2026-10-09T20:54:24.642303Z.
The service enforces freshness; do not assume this file stays usable for future
demos. Dashboard retrieval currently does not save refreshed snapshots. Plan a
fresh, validated fallback preparation step and test its original timestamps.

The remaining plan stages are Step 11 (frontend integration), Step 12 (full
verification) and Step 13 (packaging/submission). Start planning those now, but
retain the above verification gates before declaring the branch integrated.
