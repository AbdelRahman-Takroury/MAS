# Integration decisions

## Historical source notes (not Git state of this folder)

- Abdel_Rahman: `ca7a641fe5ea4c38bbbe78b7d2503f1dfb252894`, plus the local uncommitted step 6–10 services, routes, knowledge data and tests.
- Mo3taz: `d6ce17d0fa5024e5c1f66fff9a155d72b691dfe1`.
- Originals remain at `../MAS` and `../teammate-source`. This directory is the merged working copy. No credentials or databases were copied.

## Comparison and choices

| Area | Conflict / missing feature | Decision |
| --- | --- | --- |
| UI | Only Mo3taz has the complete vanilla dashboard, bilingual PDF and voice controls | Preserve HTML/CSS/JS and assets; serve only `public`, never repository root |
| Persistence | Two incompatible farm/season schemas, SQLite create-all versus PostgreSQL migrations | Keep Abdel_Rahman's User → Farm → Plot → CropSeason schema and Alembic; additive migration for harvests/sales and planning fields |
| API | Dashboard DTOs differ from existing public contracts | Thin `/api/ui` translation layer over the same records/services; keep `/api/farms`, dashboard, assistant and simulation contracts |
| Calculators | Mo3taz embeds a second repository and imports its engines dynamically | Keep one existing tested set of deterministic engines; omit nested duplicate repository |
| Assistant | Two Groq clients and different default models | Keep reviewed retrieval, citations and fallback from Abdel_Rahman; retain `openai/gpt-oss-20b` |
| Records | Mo3taz supports harvests/sales and partial farm profiles; canonical domain requires complete profiles and confirmed irrigation | Add harvest/sale records; require complete supported tomato/drip profiles, never fabricate coordinates or efficiency |
| Forecast finance | Manually entered projected revenue conflicts with quantity × price | Use engine results; expected harvest denotes **remaining marketable quantity**, not total harvest; actual sales are added exactly once |
| UI writes | Write methods exist but no record-entry forms | Add a compact management dialog without redesigning dashboard |
| Demo/security | Mock mode is the default; neither app has authentication | Live same-origin API by default; explicit `?demo=1` mode; local single-user demonstration only |
| Voice/catalog | Azure TTS and static supplier snapshot unique to Mo3taz | Preserve optional server-only TTS and dated catalog with price/availability disclaimer |

The source hashes above are historical integration notes, not verified local commits: this delivered folder has no Git metadata. Current evidence is in `integration_readiness.md`.

No old database is imported automatically. Existing canonical databases can be migrated only after backup; do not point verification runs at production. Teammate database import needs an explicit mapping/export decision and is not automatic.
