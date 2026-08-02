# Minimal employee and analyst portal

Milestone 3, Task 3.3 provides the first browser vertical slice. The React application is a
thin client over the tenant-safe catalogue, draft, ticket, and public-comment APIs. It does
not contain workflow, routing, SLA, attachment, notification, or AI behavior.

## User journey

Employees can browse published catalogue projects and request types, render the effective
request form, create and edit a draft, review it, explicitly confirm submission, list their
tickets, open ticket details, and exchange public comments. Analysts can navigate published,
authorized queues, safely search and page their results, open ticket details, view classified
activity, and add either a public comment or an internal note.

Request-specific controls are generated from the API form contract. Field labels, help text,
required flags, select options, and restricted conditional rules are configuration data; the
frontend has no Oracle- or request-type-specific form components. Impact and urgency remain
standard ticket inputs whose authoritative priority calculation occurs on the API.

Loading, empty, error, success, unauthorized, validation, and conflict states are rendered in
accessible status or alert regions. Controls use native labels, headings, landmarks, and focus
outlines. The layout collapses to a single column on narrow screens.

## Identity and security

The two persona buttons are development-only identities (`DEV/customer` and `DEV/agent`) and
depend on `DEVELOPER_IDENTITY_ENABLED=true`. Production authentication remains OIDC and must not
enable these selectors. The browser never sends tenant, role, support-group, or project authority;
the API derives all scope from its authenticated request context.

Draft changes send the current `row_version` in the body and `If-Match`; stale writes return a
visible 409 recovery state. Ticket submission and public comments use a fresh idempotency key.
Changing persona clears the query cache before authentication state changes, preventing one local
persona from seeing another persona's cached data. Public comment APIs enforce reporter or analyst
scope, tenant filtering, centralized permission checks, immutable events, and audit records.

The production web image runs as the unprivileged Node user, uses a read-only container filesystem,
serves only built assets with SPA fallback, and supplies CSP, referrer, and content-type headers.

## Generated API client

`packages/api-client/src/generated.ts` is generated from `docs/api/openapi.json`; do not edit it
manually. Regenerate both contracts after an API change:

```powershell
uv run python -m apps.api.app.openapi
pnpm openapi:client
pnpm exec prettier --write docs/api/openapi.json packages/api-client/src/generated.ts
```

## Local development

After installing, migrating, and seeding PostgreSQL as described in the existing operations
guides, enable developer identities and start the API and web application in separate PowerShell
windows:

```powershell
$env:APP_ENV = "development"
$env:DEVELOPER_IDENTITY_ENABLED = "true"
$env:OBJECT_STORAGE_ENABLED = "false"
uv run python -m apps.api.app.server
```

```powershell
$env:VITE_API_URL = "http://127.0.0.1:8000"
pnpm --filter @fusion-helpdesk/web dev
```

The server module deliberately uses a selector event loop on Windows because async Psycopg is not
compatible with the default Proactor loop. Linux containers continue to use the API image entry
point. `docker compose --profile application up -d --build` builds the web image and exposes it at
`http://127.0.0.1:3000` by default.

## Verification

Component tests cover dynamic controls, accessible state handling, and persona entry. The
Playwright test creates an isolated PostgreSQL Compose project on port 55449, installs and migrates
the physical baseline, loads deterministic development fixtures, starts API and web processes,
and proves this journey:

1. employee reports an Oracle Fusion error and explicitly submits it;
2. analyst sees the new ticket in the Unassigned queue and posts a public comment;
3. employee signs back in and sees the analyst comment.

Run it with `pnpm test:e2e`. Global teardown removes only the named test project and its isolated
volume. Playwright browser binaries must already be present (`pnpm exec playwright install
chromium`).

Queue administration, attachments, SLA processing, notifications, and AI remain intentionally
deferred.
