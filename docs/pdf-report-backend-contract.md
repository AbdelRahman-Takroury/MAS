# Smart Farm AI — Farm PDF Report (frontend)

The dashboard generates a bilingual PDF **in the browser** from a frozen snapshot of the currently selected tomato farm. No new database tables are required. The report never invents harvest weights, market prices, fertilizer doses, irrigation run times, diagnoses, or source titles.

## What the frontend already uses

Same assumed endpoints as `js/api.js`:

| Endpoint | Role in the report |
| --- | --- |
| `GET /farms/{id}` | Farm profile and tomato crop details |
| `GET /farms/{id}/weather` | Weather days, timestamp (`date` / `fetched_at`) |
| `GET /farms/{id}/irrigation` | Confirmed records + `estimate` if the backend calculated one |
| `GET /farms/{id}/inspections` | Reminder titles |
| `GET /farms/{id}/financials` | JOD costs, revenue, fertilizer budget |
| `GET /farms/{id}/recommendations` | Same `Recommendation` objects as the dashboard dialog (`SFA_REC.resolve`) |

Recommendations must follow `js/types.js`. Text `{placeholders}` are filled from that item’s `evidence` so the PDF cannot drift from the dialog.

## Optional fields (no schema change required)

If these are **absent**, the PDF prints **Not available** / **غير متوفر**. If they are **present and numeric / structured**, they are shown.

### `GET /farms/{id}/financials` (optional)

```json
{
  "expected_harvest_kg": 4200,
  "actual_harvest_kg": 3800,
  "fertilizer_options": [
    { "name": { "en": "Option A (reviewed)", "ar": "الخيار أ (مراجَع)" }, "cost_jod": 120 }
  ]
}
```

Derived only when both inputs exist (not stored, not guessed):

- projected profit = `projected_revenue_jod − projected_costs_jod`
- recorded profit = `actual_revenue_jod − recorded_costs_jod`
- cost per kg = `projected_costs_jod ÷ expected_harvest_kg`
- break-even JOD/kg = `projected_costs_jod ÷ expected_harvest_kg`
- fertilizer budget share = `fertilizer_budget_jod ÷ recorded_costs_jod`

Do **not** send placeholder yields or prices. Omit the field until a reviewed calculation exists.

### `GET /farms/{id}/inspections` (optional per reminder)

```json
{ "id": "r1", "title": { "en": "Inspect lower leaves", "ar": "افحص الأوراق السفلية" }, "due_date": "2026-10-12", "reason": { "en": "Early blight risk window", "ar": "فترة خطر اللفحة المبكرة" } }
```

`reason` must come from farm data or a reviewed rule. The PDF will not fabricate a reason.

### `GET /farms/{id}/weather` (optional)

```json
{ "source": "Jordan Meteorological Department", "fetched_at": "2026-10-09T08:00:00+03:00" }
```

If `source` is omitted, the PDF says the farm weather API did not supply a provider name (or labels sample data as simulated). Do not let the frontend guess a provider.

## What remains backend work

1. Serve real farm JSON (today the UI uses labelled sample data when `API_BASE` is unset).
2. Supply reviewed irrigation **estimates**, fertilizer **options/costs**, harvest **kg**, and weather **source/timestamp** when those calculations exist.
3. `GET /farms/{id}/recommendations` with bilingual `Recommendation` objects and evidence — otherwise the dashboard/PDF keep using local demo rules (tagged `demo`).
4. No PDF endpoint is required; generation is client-side. A future server-side PDF is optional and must embed an Arabic-capable font and run letter-joining for Arabic.

## Frontend set-up

```js
window.SFA_CONFIG = { API_BASE: 'http://localhost:8000/api' };
```

Fonts: `assets/fonts/Amiri-Regular.ttf` and `Amiri-Bold.ttf` (SIL Open Font License). Library: vendored jsPDF 2.5.2 (`js/vendor/jspdf.umd.min.js`).
