# Shared API contract

The Pydantic models in `backend/app/schemas/` are the source of truth. FastAPI
will generate OpenAPI from them. Files in `contracts/examples/` are executable
examples for frontend mocks and tests.

Salah's engine contracts remain internal. The dashboard integration service
maps them as follows:

| Engine status | API status | API data kind |
|---|---|---|
| `calculated` | `estimated` | `calculated` |
| `partial` | `missing_data` | `calculated` |
| `unavailable` | `unavailable` | `calculated` |
| weather `live` | `ok` | `live` |
| weather `cached` | `estimated` | `cached` |

Contract rules:

- Units are included in field names.
- Unknown results are `null`, never fabricated as zero.
- `status` describes usability; `data_kind` describes origin.
- All module responses expose sources, assumptions, warnings, and missing inputs.
- Simulations never persist overrides.
- Recommendations never create confirmed irrigation events.
- Inspection `cannot_assess` is distinct from assessed conditions with no alert.
