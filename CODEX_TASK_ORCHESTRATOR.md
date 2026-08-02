# Codex Task Orchestrator

## Purpose

Use this document as the execution control file for Codex in Visual Studio Code.

It tells Codex how to:

1. Validate the completed but uncommitted task.
2. Stop safely when validation fails.
3. Commit and tag a successfully completed task.
4. Proceed to exactly one approved next task.
5. Leave the newly implemented task uncommitted for human review.

This document does not replace `BUILD_SPEC.md`.

## Authority Order

Use the following precedence:

1. `BUILD_SPEC.md`
2. `docs/PRODUCTION_ARCHITECTURE_ADDENDUM.md`
3. This document
4. `docs/PRODUCT_BACKLOG.md`
5. Module-specific documentation
6. Existing code and tests

When requirements conflict, follow the highest-authority document and report the conflict.

## Repository

```text
D:\WIP-Projects Wrok\HelpdeskAgent
```

## Current Control State

```yaml
review_target:
  milestone: 3
  task: 3.1
  name: Service catalogue and dynamic request-form foundation
  status: implemented_uncommitted
  commit_message: "feat(catalog): add service catalogue and dynamic request forms"
  git_tag: "milestone-3-task-3.1"

next_approved_task:
  milestone: 3
  task: 3.2
  name: Ticket draft and submission foundation
  completion_behavior: leave_uncommitted_for_review
```

## Global Execution Rules

- Work only inside the repository.
- Do not modify the PostgreSQL physical baseline.
- Use Alembic for every post-baseline schema change.
- Do not rewrite completed milestones.
- Do not silently broaden scope.
- Do not implement more than one new task during this run.
- Do not commit the newly implemented next task.
- Never commit secrets, tokens, credentials, `.env`, generated caches, or local database files.
- Do not disable tests or security checks to obtain a passing result.
- Do not weaken authorization, RLS, migration, or secret-scanning policies.
- Do not change tests merely to hide an implementation defect.
- Preserve tenant isolation and immutable history.
- Keep PostgreSQL as the system of record.
- Use UTC timestamps and explicit PostgreSQL schemas.
- Keep routers thin and business rules in application/domain services.
- Do not expose SQLAlchemy models directly through APIs.
- Use real PostgreSQL for PostgreSQL-specific behavior.
- GNU Make is unavailable on the Windows host. Run underlying commands directly and validate Makefile targets through the established container-based method.

## Phase 1 — Establish Repository State

Run:

```powershell
Set-Location "D:\WIP-Projects Wrok\HelpdeskAgent"

git status
git diff --stat
git diff --check
git log --oneline --decorate -10
git tag --list
```

Confirm:

- The working tree contains only Milestone 3, Task 3.1 changes.
- There are no unrelated generated files.
- There are no secrets or local environment files.
- The latest committed tag represents the prior completed task.
- The current Alembic revision chain is linear.
- The physical-baseline package is unchanged.

If unrelated changes exist:

1. List them.
2. Do not discard them.
3. Do not include them in the milestone commit.
4. Stop and report the scope conflict unless they are conclusively governed generated outputs.

## Phase 2 — Validate Milestone 3, Task 3.1

Read:

- `BUILD_SPEC.md`
- `docs/PRODUCTION_ARCHITECTURE_ADDENDUM.md`
- `docs/PRODUCT_BACKLOG.md`
- catalogue module source
- catalogue tests
- catalogue-related migrations
- identity and authorization modules
- RLS and transaction-context code
- OpenAPI contract
- development fixtures
- operations documentation

### Required Functional Validation

Confirm that the implementation provides authenticated, read-only access to:

- Visible service projects
- Service hierarchy
- Published request types
- Exact published request-form versions
- Typed fields
- Ordered options
- Stable version identifiers

Confirm:

- Anonymous catalogue access is rejected.
- Cross-tenant catalogue entries are not returned.
- Inactive projects are hidden.
- Draft request-type versions are hidden.
- Retired versions are hidden.
- Future-effective versions are hidden.
- Expired versions are hidden.
- Published-version selection is deterministic.
- Overlapping effective published versions fail safely.
- Form fields are returned in deterministic display order.
- Field options are returned in deterministic display order.
- Inactive options are hidden.
- Unknown request types return the project-standard not-found response.
- Unauthorized access follows the project’s non-disclosure policy.
- Client input cannot inject tenant, role, audience, project, or permission scope.
- The form response includes immutable request-type or form-version identifiers.
- No ticket creation or frontend functionality was introduced.

### Required Architecture Validation

Confirm:

- Catalogue routers contain HTTP concerns only.
- Application services coordinate use cases.
- Repositories contain database query details.
- Authorization uses the central policy framework.
- No role-name checks are scattered through route handlers.
- Repository queries use explicit schemas.
- Tenant and effective-date filters are applied.
- Transaction-local tenant and user context is applied.
- No generic arbitrary-table repository was introduced.
- SQLAlchemy entities are not returned directly.
- No duplicate catalogue tables were created.
- Published configuration is treated as immutable.
- Any Alembic migration is narrowly scoped and justified.
- The physical baseline remains unchanged.

### Required Security Validation

Confirm:

- Authorization runs before protected data is returned.
- RLS regression tests continue to pass where enabled.
- Concurrent requests do not leak tenant or user context.
- Logs do not expose SQL, credentials, tokens, claims, or sensitive configuration.
- Error responses use RFC 7807 and include correlation IDs.
- Diagnostics and development-identity controls remain production-safe.
- OIDC validation and PostgreSQL-authoritative roles remain intact.

### Required Test and Quality Validation

Run all configured checks, including the underlying commands for:

- Ruff formatting
- Ruff linting
- mypy strict mode
- Python unit tests
- PostgreSQL catalogue integration tests
- Identity and authorization regression tests
- OIDC regression tests
- RLS regression tests
- Alembic upgrade, downgrade, history, and policy validation
- OpenAPI validation
- Prettier
- ESLint
- TypeScript checking
- Vitest
- Docker Compose validation
- API image build
- API health and readiness
- Gitleaks
- pip-audit
- pnpm audit
- Trivy filesystem scan
- Trivy API image scan
- `git diff --check`

Do not rely only on a prior completion report. Run the checks in the current working tree.

### Validation Decision

When any required check fails:

1. Diagnose the failure.
2. Fix only defects within Milestone 3, Task 3.1 scope.
3. Rerun the affected check.
4. Rerun the full required suite when the change could affect other modules.
5. Do not proceed to Task 3.2 until all required checks pass.
6. If the failure cannot be safely corrected within Task 3.1, stop and report:
   - failed check
   - root cause
   - files involved
   - recommended remediation
   - whether the working tree remains safe

When every required check passes, continue to Phase 3.

## Phase 3 — Commit and Tag Task 3.1

Before staging:

```powershell
git status
git diff --stat
git diff --check
```

Stage only Task 3.1 files:

```powershell
git add .
git status --short
```

Review the staged changes:

```powershell
git diff --cached --stat
git diff --cached --check
```

Commit:

```powershell
git commit -m "feat(catalog): add service catalogue and dynamic request forms"
git tag milestone-3-task-3.1
```

Verify:

```powershell
git status
git show --stat --oneline HEAD
git tag --list
```

Required state before proceeding:

```text
Working tree clean
Tag milestone-3-task-3.1 exists
No physical-baseline files changed
No secrets committed
```

If commit or tag creation fails, stop and report the failure. Do not start Task 3.2.

## Phase 4 — Implement Milestone 3, Task 3.2

### Task Name

Ticket draft and submission foundation

### Objective

Implement the backend ticket-draft and confirmed ticket-submission foundation.

An authenticated employee must be able to:

1. Create a ticket draft from a published request form.
2. Update their own unsubmitted draft.
3. Validate the draft against the exact immutable request-form version.
4. Review normalized ticket details.
5. Explicitly confirm submission.
6. Create exactly one permanent ticket.
7. Receive a unique project ticket key.
8. Retrieve the submitted ticket and immutable creation history.

### Scope Boundary

Do not implement:

- Analyst assignment
- Routing-rule evaluation
- Analyst queues
- Workflow transitions after initial state
- Attachments
- SLA processing
- Approvals
- Notifications
- Inbound email
- Knowledge ingestion
- Retrieval
- OpenAI or Anthropic providers
- AI agents
- Frontend pages
- Reporting models
- CMDB
- Major incident management
- Problem management
- Change management

### Required Domain Behavior

#### Ticket Draft

Implement a draft aggregate using existing structures where possible.

A draft must retain:

- Tenant
- Draft owner
- Requested-for user where authorized
- Service project
- Service node
- Request type
- Exact request-type or form version
- Work type
- Application environment
- Summary
- Description
- Structured custom-field values
- Impact
- Urgency
- Calculated priority
- Draft state
- Created timestamp
- Updated timestamp
- Row version
- Expiration timestamp where applicable

Supported states:

```text
DRAFT
READY_FOR_REVIEW
SUBMITTED
EXPIRED
CANCELLED
```

A submitted draft is immutable except for controlled archival metadata.

Do not use a permanent ticket row as an editable draft unless explicitly required by `BUILD_SPEC.md`.

#### Authorization

Use the central policy framework.

Implement only permissions required for this task:

```text
TICKET_DRAFT_CREATE
TICKET_DRAFT_READ_OWN
TICKET_DRAFT_UPDATE_OWN
TICKET_SUBMIT
TICKET_READ_OWN
```

Enforce:

- Customers can create and update only their own drafts.
- Requested-for behavior requires explicit authorization.
- Cross-tenant access fails.
- One customer cannot access another customer’s draft.
- Client input cannot override tenant, reporter, role, permission, priority, workflow status, or configuration versions.
- Role checks do not appear directly in routers.

#### Configuration-Version Binding

At draft creation:

- Resolve the active published request type.
- Resolve the exact immutable form version.
- Store the version on the draft.
- Resolve the applicable initial workflow version.
- Store that workflow version on ticket creation.
- Do not silently upgrade the draft to a later form version during submission.

Document the policy for a draft whose stored form version is later retired or revoked.

#### Validation and Normalization

Validate against the stored immutable form version:

- Required fields
- Data types
- Length limits
- Numeric ranges
- Date and datetime formats
- Single-select options
- Multi-select options
- Active options
- User references
- Service-node references
- Application-environment references
- Restricted conditional rules already supported
- Unknown-field rejection
- Duplicate-field rejection

Normalize:

- Whitespace
- Empty strings
- Date/time representation
- Boolean values
- Numeric values
- Multi-select ordering where order is not meaningful
- Safe text length

Do not execute JavaScript, SQL, Python, Jinja, templates, or LLM-generated expressions.

Return structured RFC 7807 validation errors.

#### Deterministic Priority

Calculate final priority from the active impact-and-urgency matrix.

- The client may supply permitted impact and urgency.
- The client cannot directly assign priority.
- Store impact, urgency, priority, and applicable matrix/version reference where supported.
- Fail safely when no matrix entry exists.
- Fail safely when overlapping active entries exist.
- Do not use an LLM.

#### Draft APIs

Implement authenticated endpoints consistent with project conventions:

```http
POST   /api/v1/ticket-drafts
GET    /api/v1/ticket-drafts/{draft_id}
PATCH  /api/v1/ticket-drafts/{draft_id}
POST   /api/v1/ticket-drafts/{draft_id}/validate
POST   /api/v1/ticket-drafts/{draft_id}/submit
DELETE /api/v1/ticket-drafts/{draft_id}
```

Requirements:

- Use optimistic concurrency.
- Require row version or `If-Match` for updates.
- Return 409 for stale versions.
- Do not allow edits after submission.
- Audit cancellation.
- Do not physically delete submitted drafts.

#### Explicit Submission

Submission must:

1. Authenticate and authorize.
2. Load and lock the draft.
3. Verify ownership.
4. Verify expected row version.
5. Verify the draft is submittable.
6. Revalidate against the stored form version.
7. Recalculate deterministic priority.
8. Allocate the next project ticket number safely.
9. Create the ticket.
10. Capture request/form and workflow versions.
11. Persist custom-field values.
12. Append `TICKET_CREATED`.
13. Mark the draft submitted.
14. Persist idempotency result.
15. Commit in one transaction.
16. Return the ticket key and representation.

No permanent ticket may exist before explicit confirmation.

#### Idempotency

Require `Idempotency-Key` on submission.

Use the existing idempotency foundation.

- Scope by tenant and operation.
- Store request hash.
- Prevent concurrent duplicate submission.
- Return the original result for identical retries.
- Return 409 for the same key with a different request.
- Use processing leases and retryable failure states.
- Do not leave records permanently stuck in processing.
- Do not create duplicate tickets or counters.

#### Ticket Numbering

Use the existing project ticket counter.

- Produce keys such as `ERP-1`.
- Allocate transactionally.
- Do not use `MAX(...) + 1`.
- Enforce uniqueness in PostgreSQL.
- Roll back failed submissions.
- Document acceptable gaps if the safe strategy can create them.
- Test parallel submissions.

#### Initial Workflow State

- Resolve the configured initial state for the immutable workflow version.
- Reject missing initial states.
- Reject multiple conflicting initial states.
- Store workflow version and current status.
- Do not accept internal status IDs from the client.
- Do not implement later transitions.

#### Custom Values

- Preserve data type.
- Preserve field or field-version references.
- Prevent duplicate values for the same field.
- Use typed structures where the baseline supports them.
- Preserve values needed to reproduce the submitted form.
- Do not expose internal-only values to customers.

#### Immutable Ticket Event

Append `TICKET_CREATED` in the submission transaction.

Record safe metadata including:

- Ticket
- Tenant
- Actor
- Event type
- Timestamp
- Correlation ID
- Request ID
- Source channel
- Initial status
- Project
- Request type
- Request/form version
- Workflow version
- Priority

Do not store tokens, secrets, attachment contents, or unnecessary personal information.

#### Outbox Boundary

When required by `BUILD_SPEC.md`, create same-transaction outbox events:

```text
ROUTE_TICKET
START_SLA
NOTIFY_TICKET_CREATED
```

Do not implement consumers or downstream behavior.

#### Customer Ticket Read APIs

Implement minimal retrieval:

```http
GET /api/v1/tickets/{ticket_key}
GET /api/v1/my/tickets
```

Return only customer-safe fields.

Do not expose:

- Internal comments
- Routing details
- Sensitive audit payloads
- Other users’ private tickets
- Cross-tenant records

Use stable pagination for `/api/v1/my/tickets`.

### Database Rules

- Use Alembic for every schema change.
- Do not modify the physical baseline.
- Confirm structures are missing before creating migrations.
- Keep migrations narrowly scoped.
- Use explicit schema, index, and constraint names.
- Include downgrade logic.
- Run destructive-migration guards.
- Test upgrade, downgrade, and re-upgrade.
- Do not add unrelated routing, SLA, attachment, email, AI, or knowledge structures.

### Testing Requirements

Add unit and real PostgreSQL integration tests for:

- Anonymous draft creation rejection
- Own-draft creation
- Cross-tenant rejection
- Unpublished form rejection
- Exact form-version binding
- Unknown custom-field rejection
- Required-field validation
- Text-length validation
- Numeric-range validation
- Invalid and inactive options
- Multi-select normalization
- Environment authorization
- Deterministic priority
- Missing matrix failure
- Overlapping matrix failure
- Optimistic concurrency
- Cross-user draft isolation
- Explicit confirmation requirement
- One-ticket submission
- Correct project key
- Parallel unique keys
- Identical idempotent retry
- Idempotency-key conflict
- Concurrent duplicate submission
- Full rollback on failed submission
- Correct workflow version and initial state
- Immutable creation event
- Submitted-draft immutability
- Own-ticket retrieval
- Cross-user and cross-tenant ticket isolation
- Stable pagination
- Transaction context isolation
- RLS regression
- OpenAPI coverage
- Sensitive logging protection
- Unchanged physical baseline

Use PostgreSQL, not SQLite, for PostgreSQL behavior.

### Documentation Requirements

Document:

- Draft versus submitted ticket
- Explicit confirmation
- Exact form-version binding
- Validation and normalization
- Priority calculation
- Idempotency
- Ticket numbering
- Initial workflow state
- Custom values
- Immutable creation event
- Outbox boundary
- Customer visibility
- Optimistic concurrency
- API examples
- Test commands
- Known limitations
- Deferred routing, SLA, notifications, attachments, and analyst behavior

### Full Validation

Run all configured checks:

- Ruff formatting and linting
- mypy strict
- Python unit tests
- PostgreSQL ticket integration tests
- Identity/OIDC/authorization regression tests
- RLS tests
- Alembic upgrade/downgrade/policy checks
- OpenAPI validation
- Prettier
- ESLint
- TypeScript
- Vitest
- Docker Compose validation
- API image build and health
- Gitleaks
- pip-audit
- pnpm audit
- Trivy filesystem and API image
- `git diff --check`

## Phase 5 — Stop for Human Review

After Task 3.2 is implemented and validated:

- Do not commit.
- Do not tag.
- Do not begin Task 3.3 or Milestone 4.
- Leave the working tree containing only Task 3.2 changes.

Provide a completion report containing:

1. Draft and ticket architecture
2. Authorization behavior
3. Form-version binding
4. Validation and normalization
5. Priority calculation
6. Idempotency behavior
7. Ticket-number allocation
8. Initial workflow state
9. Custom-field persistence
10. Ticket event and outbox behavior
11. Endpoints
12. Database migrations
13. OpenAPI changes
14. Files changed
15. Tests and security results
16. Deferred items
17. Known risks
18. Recommended next task

## Failure Protocol

Stop immediately and report instead of continuing when:

- The physical baseline changed unexpectedly.
- A secret is detected.
- Alembic history is conflicting or non-linear.
- A required test cannot be made to pass safely.
- The repository contains unrelated uncommitted work.
- A required database structure conflicts with `BUILD_SPEC.md`.
- A destructive migration requires unapproved data loss.
- Tenant isolation or authorization cannot be proven.
- The next task requires an explicitly deferred feature.

## Updating This Document After Task 3.2

After Task 3.2 is reviewed and committed, update only the `Current Control State`
section:

```yaml
review_target:
  milestone: 3
  task: 3.2
  name: Ticket draft and submission foundation
  status: implemented_uncommitted
  commit_message: "feat(ticketing): add ticket draft and submission foundation"
  git_tag: "milestone-3-task-3.2"

next_approved_task:
  milestone: 4
  task: 4.1
  name: Workflow transition engine
  completion_behavior: leave_uncommitted_for_review
```

Replace Phase 2 and Phase 4 task-specific sections when advancing to a different
task family. Keep the global rules, failure protocol, and commit discipline.
