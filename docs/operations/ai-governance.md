# AI governance administration

Task 11.5E adds read-only, tenant-scoped AI governance visibility at
`/admin/ai`. It does not add a runtime control plane. The browser cannot edit
provider settings, model assignments, policies, budgets, retrieval settings,
or circuit state.

## Authorization and API

All endpoints require `AI_OVERSIGHT`, which is granted only to `AI_ADMIN` and
`PLATFORM_ADMIN`. Privileged access and denied attempts use the existing
append-only security-event path.

```text
GET /api/v1/admin/ai
GET /api/v1/admin/ai/policies
GET /api/v1/admin/ai/policies/{feature_policy_id}
GET /api/v1/admin/ai/usage
```

Policy and usage queries always include the authenticated tenant. Global
policy/configuration rows may be displayed read-only; other-tenant rows and
identifiers are excluded. Child configuration rows are reached through an
owning global-or-tenant parent. The same behavior is tested with optional RLS
enabled and disabled through the non-owner application login.

The usage endpoint defaults to seven days, accepts only a timezone-aware
half-open range, and rejects ranges longer than 90 days. Costs are estimates
and remain separated by currency. Ledger totals include completed provider
calls only. Historical role and true use-case dimensions are unavailable
because the ledger does not store them.

## Safety state

The page distinguishes these conditions instead of reducing all failures to
"disabled":

- platform environment switch disabled;
- provider configuration incomplete;
- published retrieval configuration unavailable;
- ready to attempt, with provider availability explicitly not probed;
- individual policy disable or budget hard stop;
- current-process circuit open.

`AI_GLOBALLY_ENABLED` remains environment-owned. Changing it requires a
service restart and follows the AI-disable runbook. A tenant policy cannot
override it. No endpoint performs provider traffic or accepts an enable,
disable, reset, or configuration command.

Circuit observations are process-local. They are keyed by safe provider/model
aliases, disappear on process restart, and do not represent cluster-wide
health. The page does not offer manual reset.

## Secret boundary

Responses use explicit Pydantic DTO allowlists. They never serialize settings
objects, provider endpoint URLs, deployment values, credentials, database or
Redis URLs, OIDC material, authorization headers, prompt text, tool
definitions, retrieval weights, vectors, retrieved content, or model output.
Safe provider status is limited to configured/enabled booleans, alias keys,
and `not_probed` availability.

## Knowledge and retrieval interaction

Governance visibility does not alter the authorization-first retrieval path.
Only active, approved, current, validated, published documents and their
pinned processing/embedding versions are eligible. Audience, classification,
principal, support-group, business-unit, source, release, effective-date, and
review-date predicates continue to execute in SQL. Retiring a document removes
it from active retrieval; unpublished replacements and newer unpinned
processing versions remain invisible.

## Performance and rollback

Business-query ceilings are three `SELECT` statements for the overview and
one statement each for policy list, policy detail, and usage. Usage aggregation
is bounded to 90 days and uses the existing tenant/time ledger index. The
frontend performs three initial requests, one optional policy-detail request,
and no polling.

Task 11.5E requires no Alembic revision or runtime grant. Rollback is an
application/UI/OpenAPI revert; it does not change database state, provider
configuration, or the production release.
