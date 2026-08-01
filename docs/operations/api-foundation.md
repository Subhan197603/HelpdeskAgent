# API foundation operations

## Run modes

Install locked dependencies and start the platform with `make bootstrap` and `make up`. Install
the database baseline and local non-owner runtime login with `make db-install`. For a host-run
API, use host-addressable dependency URLs:

```sh
DATABASE_URL=postgresql+psycopg://helpdesk:helpdesk@localhost:5432/helpdesk \
REDIS_URL=redis://localhost:6379/0 \
OBJECT_STORAGE_ENDPOINT=http://localhost:9000 \
CLAMAV_HOST=localhost make api
```

PowerShell users can set the same environment variables before `make api` or run
`uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000`. Reload is opt-in with
`API_RELOAD=true` and is rejected outside development and test environments.

To build and run the container:

```sh
make db-install
docker compose --profile application up -d --build --wait api
```

The image runs as a non-root user, and Compose uses a read-only filesystem, loopback port
publishing, `no-new-privileges`, dependency health conditions, and a liveness health check.

## Health and request IDs

- `GET /health/live` checks only the process and event loop.
- `GET /health/ready` checks PostgreSQL, Redis, and object storage. ClamAV is reported but is
  required only when `CLAMAV_REQUIRED=true`.
- `GET /api/v1/health` has the same readiness semantics for versioned clients.

Health payloads expose status and timing, never URLs, credentials, hostnames, stack traces, or
provider errors. Required dependency failure returns HTTP 503.

Clients may send a UUID in `X-Correlation-ID`. Invalid or missing values are replaced, and the
selected value is returned in the response and RFC 7807 error payload. A separate generated
`X-Request-ID` identifies one request. Context variables isolate concurrent requests.

Protected routes use the database-backed local identity and centralized authorization foundation
described in [Developer identity and authorization](developer-identity.md) or the provider-neutral
[production OIDC flow](oidc-authentication.md). Health endpoints intentionally retain anonymous
request contexts.

## Configuration and logging

`.env.example` documents all foundation settings. Database pool behavior is controlled by
`DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT`, and
`DATABASE_POOL_RECYCLE`. Production rejects debug/reload, developer identity, wildcard CORS or
trusted hosts, non-JSON logs, a missing telemetry endpoint, and missing object-store credentials.
Secret settings use redacted Pydantic values.

Development logs are readable. `JSON_LOGS=true` emits structured JSON with timestamp, severity,
service/environment, logger, message, correlation/request IDs, safe tenant/user references,
HTTP status and duration, outcome, trace ID when supplied, and error code. Application logging
does not record headers, cookies, bodies, credentials, prompts, documents, email, or attachments.

## Transactions and unit of work

Application services should open `SqlAlchemyUnitOfWork`, perform work through narrowly scoped
repositories added by later tasks, and explicitly commit. Exiting without a commit rolls back and
always closes the owned async session.

When enabled, the transaction hook uses parameterized PostgreSQL
`set_config('app.tenant_id', value, true)` and `set_config('app.user_id', value, true)`. The final
`true` is PostgreSQL's transaction-local equivalent of `SET LOCAL`; the values are omitted for an
anonymous context and reset before a pooled connection is reused. `RLS_ENABLED` remains false.
The authenticated integration suites exercise this mode with both developer and production
identity resolution.

## Validation

Run `make format-check`, `make lint`, `make typecheck`, and `make test`. `make test-integration`
creates isolated Compose projects and uses real PostgreSQL and Redis; it also builds the API image
and verifies liveness/readiness. No SQLite substitute is used.

Known limitations: the S3-compatible probe checks the provider readiness endpoint, not bucket
authorization; trace extraction and OpenTelemetry export are configuration-only; and business
routes and outbox behavior are deferred. Database changes follow the separate
[Alembic operations guide](database-migrations.md).
