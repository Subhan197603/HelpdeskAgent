# Developer identity and authorization

## Purpose and safety boundary

Developer identity is a local-only substitute for production OIDC, which is deferred to the next
assigned identity task. It is disabled by default, and settings validation refuses to start a
production process when it is enabled. It is not an identity provider, does not validate tokens,
and must never be exposed in a shared or production environment.

The client sends one selector in `X-Developer-User` using `TENANT_CODE/external_subject`, for
example `DEV/agent`. The selector only locates an existing PostgreSQL user. Tenant ID, user ID,
roles, support groups, business unit, active state, and permissions come from the database.
Requests supplying `X-Tenant-ID`, `X-User-ID`, `X-Roles`, `X-Permissions`,
`X-Support-Group-IDs`, or `X-Business-Unit-ID` fail authentication.

## Local setup and personas

Install and migrate the database, opt into fixtures, then enable the mode in the untracked `.env`:

```sh
make db-install
make db-stamp-baseline
make migrate
make seed
```

```dotenv
APP_ENV=development
DEVELOPER_IDENTITY_ENABLED=true
DEVELOPER_IDENTITY_HEADER=X-Developer-User
```

`make seed` refuses to run unless `APP_ENV=development`. The deterministic fixture is separate
from `install_all.sql`, uses only `.invalid` addresses, and provides:

| Selector               | Role               |
| ---------------------- | ------------------ |
| `DEV/platform-admin`   | `PLATFORM_ADMIN`   |
| `DEV/project-admin`    | `PROJECT_ADMIN`    |
| `DEV/support-manager`  | `SUPPORT_MANAGER`  |
| `DEV/agent`            | `AGENT`            |
| `DEV/customer`         | `CUSTOMER`         |
| `DEV/approver`         | `APPROVER`         |
| `DEV/knowledge-author` | `KNOWLEDGE_AUTHOR` |
| `DEV/auditor`          | `AUDITOR`          |

`DEV/inactive-user` is an intentionally inactive negative-test fixture.

```sh
curl -H "X-Developer-User: DEV/agent" http://localhost:8000/api/v1/me
```

## Authentication, context, and endpoints

Authentication establishes who the caller is; authorization separately decides what that caller
may do. Missing, malformed, unknown, or inactive identities return RFC 7807 status 401.
Authenticated callers lacking permission receive 403. Both include the correlation ID and expose
no database details.

`GET /api/v1/me` requires `IDENTITY_SELF_READ` and returns caller IDs, display name, active
business unit, effective roles, active support groups, and authentication mode. It omits email,
employee number, assignment internals, and other users. Public health routes remain anonymous even
when the developer header is present.

`GET /api/v1/identity/diagnostics` is a minimal authorization probe. It requires
`ADMIN_IDENTITY_READ`, currently granted only by explicit `PLATFORM_ADMIN` membership, and emits
a privileged-access event. It is not an identity-administration API.

Middleware creates an immutable anonymous `RequestContext` with correlation and request IDs. The
protected dependency resolves identity in one unit of work, replaces only that request's context,
and isolates concurrent tasks through `ContextVar` and ASGI state. Anonymous contexts use `None`,
never fake UUIDs.

## Repositories and policy model

The identity module has narrow queries for tenant, user, effective roles, effective support groups,
and active business unit. Every query enforces the resolved tenant. Effective roles require an
active definition, active assignment, `valid_from <= now`, and no expired `valid_to`. Groups and
memberships must both be active. Routes receive transport models rather than database rows.

Stable permission codes include planned ticket, knowledge, AI, project, environment, and tool
actions. Task 2.1 implements only:

- `IDENTITY_SELF_READ`: every authenticated caller
- `ADMIN_IDENTITY_READ`: `PLATFORM_ADMIN`

Other codes are placeholders and grant no behavior. Unknown role codes grant no permissions.
`AuthorizationResource` supports tenant, project, ownership, reporter/requested-for, participant,
support-group, business-unit, classification, environment, and tool dimensions. Cross-tenant
resources fail closed.

## PostgreSQL context and RLS

The unit of work applies parameterized `set_config(..., true)` only in an active transaction.
Authentication resolves the public tenant, installs tenant-local context, loads the tenant user,
then installs user-local context. Transaction completion discards both values; pooled sequential
and concurrent tests verify no inheritance.

RLS remains disabled by default. The optional baseline script makes these tables RLS-ready:

- Identity: `business_unit`, `app_user`, `support_group`
- Configuration: project, category, request type, custom field, application environment,
  priority matrix, retention policy
- Ticketing: ticket, event, SLA, approval, communication
- Knowledge/AI: document, conversation, agent run, feature policy, usage ledger
- Audit/integration: security event, audit event, legal hold, idempotency, notification delivery,
  email mailbox, email message

Other tables still rely on tenant-filtered repositories and service authorization. RLS is defense
in depth, not a replacement for policy checks. Tests apply optional policies in an isolated
database with the non-owner `helpdesk` login; owner visibility is tested separately to avoid a
false positive from PostgreSQL owner bypass.

## Security events

The append-only `audit.security_event` stream records successful developer authentication,
unknown/inactive/disabled attempts, direct context injection, authorization denial, and privileged
diagnostic access. Payloads contain correlation ID, request ID, mode, decision, and safe resource
IDs. They omit selector/header values, email, tokens, cookies, roles, and credentials. Production
misuse is rejected during settings validation before request handling can safely record an event.

## Migration impact, tests, and limitations

Revision `0002_identity_role_activation` adds `active_flag` to `identity.role_definition` and
`identity.user_role`; the baseline had no representation for either inactive state. Revision
`0003_rls_runtime_privileges` gives non-owner runtime group roles execute access only to the two
safe context-reader functions required by optional RLS. Both have downgrade logic. The physical
baseline is unchanged.

Run `make format-check`, `make lint`, `make typecheck`, `make test`, and
`make test-integration`.

Known limitations: production OIDC, external-directory synchronization, sessions,
configuration-driven permission mappings, caching, project-scoped administration, and business
domain authorization remain deferred. Developer selectors are bearer-like local conveniences and
are intentionally not signed credentials.
