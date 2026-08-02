# Business calendars and SLA worker

Milestone 5, Task 5.1 introduces deterministic first-response and resolution SLA processing. It
does not implement approvals or notification delivery.

## Runtime architecture

Ticket submission and later public-comment, workflow-transition, and priority-change operations
write tenant-scoped SLA input records to `integration.outbox_event` in the same transaction as the
ticket change. The worker claims those inputs with `FOR UPDATE SKIP LOCKED`, sets transaction-local
tenant context, and calls the SLA application service. A periodic scan evaluates persisted warning
and target deadlines.

The worker connects through `WORKER_DATABASE_URL` as a non-owner login inheriting only
`helpdesk_worker`. It has narrow rights to SLA runtime/event rows. A tenant-checked,
`SECURITY DEFINER` function records the first public agent response without granting the worker
general ticket-update access. Runtime errors persist only the exception class; payload contents are
not logged. The worker image and Compose service expose a health probe that verifies the configured
non-owner login can reach PostgreSQL.

## Immutable configuration and runtime references

Published or retired business-calendar versions and their working-period/exception children are
immutable. Published SLA definition and goal versions retain the baseline version-protection
rules. Each `itsm.ticket_sla` row pins the selected goal version and business-calendar version, so
later configuration publication cannot reinterpret an active SLA.

The development catalogue provides a Monday-to-Friday 09:00–17:00 Europe/London calendar, a
Christmas closure, and P1/default first-response and resolution goals. These fixtures are not part
of the production baseline.

## Business time and lifecycle

Calculations use aware UTC instants and IANA timezone data. Local schedule boundaries are resolved
deterministically across spring-forward gaps and fall-back folds. Closed holidays remove all
working time for a date; custom-hour exceptions replace the regular day. Invalid timezones,
overlapping periods, ambiguous effective versions, and ambiguous goal priorities fail closed.

The initial lifecycle supports:

- `STARTED`, `PAUSED`, `RESUMED`, `STOPPED`, `MET`, `WARNING`, `BREACHED`, and `RECALCULATED`
  immutable events;
- pausing resolution SLAs while the workflow is `WAITING_FOR_CUSTOMER` and rebuilding the deadline
  from persisted remaining business seconds on resume;
- stopping first-response SLAs on the first public analyst response and resolution SLAs on a done
  transition;
- recalculating active targets after a priority change while retaining exact new goal/calendar
  version references; and
- stable event and outbox deduplication keys plus database uniqueness constraints to prevent
  duplicate warning and breach outputs.

Customer comments are retained as explicit SLA inputs but do not alter the initial first-response
or resolution metrics. Approval processing and notification delivery remain deferred.

## Configuration

```dotenv
WORKER_DATABASE_URL=postgresql+psycopg://helpdesk_worker_login:helpdesk@localhost:5432/helpdesk
WORKER_ID=local-sla-worker
WORKER_POLL_SECONDS=1
WORKER_DUE_SCAN_SECONDS=15
WORKER_BATCH_SIZE=50
WORKER_MAX_ATTEMPTS=5
```

Production rejects the local placeholder credentials and requires JSON logging. Run the worker
from the repository root with:

```powershell
uv run python -m apps.worker.worker.main
```

## Validation

```powershell
uv run pytest apps/api/tests/test_sla.py
uv run pytest tests/integration/test_sla_engine.py -m integration
uv run pytest tests/integration/test_alembic_adoption.py -m integration
uv run python -m apps.api.app.db.migrations_cli check
```

The PostgreSQL suite installs the physical baseline, applies all Alembic migrations, enables the
optional RLS package, and processes events through the actual non-owner worker login. It verifies
exact version references, waiting-for-customer pause/resume, late-response breach behavior,
duplicate processing, warning/breach uniqueness, append-only events, and calendar-child
immutability. Calendar unit tests cover holidays, custom hours, weekends, 24x7 calendars, and both
DST boundaries.
