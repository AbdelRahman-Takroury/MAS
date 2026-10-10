# Activity validation and request retries

The canonical activity APIs and `/api/ui` share establishment-date validation.
Timestamp inputs are checked using the Asia/Amman calendar date; UI date-only
values represent local calendar days. UI serialization converts timestamps back
to Amman before extracting dates. Create, edit, and move-to-season operations
reject dates before establishment with 422. Changing the season/profile start
also rejects a date that would invalidate an existing activity.

New confirmed irrigation must be positive. UI volume/depth conversions must
remain positive at stored liter precision. Historical zero-volume rows remain
readable; no existing rows or constraints are rewritten.

## Decimal policy

Expense amounts use Decimal with at most 14 total digits and 3 decimal places,
matching Numeric(14,3), in both API layers. Unsupported precision returns 422
rather than silently rounding. Existing UI sale-price precision remains four
decimal places. Canonical liters, duration and flow now match their respective
database precision. Canonical response amounts remain JSON numbers for client
compatibility. Numeric equality and request fingerprints do not use float
comparisons; trailing decimal zeros and equivalent timestamp offsets do not
change a new receipt's identity.

## Idempotency

- Canonical expense/irrigation keys remain scoped to the crop season and route.
- UI keys remain scoped to the farm/resource (farm creation is owner-scoped).
- New canonical writes save an original-response receipt transactionally in the
  existing `write_receipts` table, as UI writes already do. The integration
  migration `20261010_0002` must already be applied; no new migration is needed.
- Identical retries return 201 and the saved original response, including after
  a subsequent edit. Different payloads using that key return 409.
- A unique-constraint collision rolls back the losing transaction and reads the
  winning receipt. Activity and receipt commit together; failed attempts cannot
  leave duplicate activities behind.
- Historical UI receipt hashes remain accepted for matching original payloads.
  Canonical records without receipts retain the legacy row-comparison behavior;
  their original pre-edit response cannot be reconstructed retroactively.
- Requests without a UI Idempotency-Key remain supported but are not deduplicated.

The browser retains keys after network errors, malformed successful responses,
408/425/429, and server failures. Concurrent identical calls share a pending
request. Confirmed success and definitive client errors release the key.
An explicit New record, selecting another operation, or selecting a record to
edit starts a fresh operation. Client integrations can call
`SFA_API.beginNewOperation()` to declare that intent. Changed payloads get their
own identity. Keys are held in page memory; retry recovery across page reloads
or browser restarts is not provided by this change.

## Verification

Run with dependencies from requirements.txt and an isolated environment:

```powershell
$env:DATABASE_URL = 'sqlite+pysqlite:///:memory:'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest -q -p no:cacheprovider
node --test tests/frontend.test.cjs
```

If the default temporary directory is unwritable, pass a fresh writable
`--basetemp` directory. Pytest owns and may clear that directory.

`test_write_integrity.py` covers dates on creation and editing, season moves,
Amman midnight boundaries, positive quantities, monetary precision, immutable
receipts and compatibility with old records. Its concurrency tests use separate
sessions/connections to a temporary SQLite file and synchronize both requests
after their initial lookup, checking identical and conflicting payloads across
both API layers. Frontend tests cover lost responses, server failures, malformed
responses, explicit new operations, definitive rejection and simultaneous calls.

Final verification: all 8 synchronized race cases passed on an isolated PostgreSQL 16.15 database, covering both API layers and identical/conflicting submissions. The fixture can repeat these checks with TEST_POSTGRES_URL pointing to a mas_handoff_* database; every test uses a unique schema. The PostgreSQL browser journey also preserved 12.345 JOD and correctly replayed the stored original result. These are local PostgreSQL process checks, not Docker lifecycle verification. No operational database was touched.
