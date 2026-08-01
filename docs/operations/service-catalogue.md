# Service catalogue and dynamic request forms

## Concepts and trust boundary

The Task 3.1 catalogue is an authenticated, read-only view of configuration already stored in the
PostgreSQL `config` schema:

- A service project is an employee-facing support domain such as ERP or BI.
- The service-node tree describes tenant services, applications, modules, and business processes.
- A work type is the internal ITSM classification associated with a request type.
- A request type is the stable employee-facing catalogue entry.
- A request-type version is the immutable published form/layout version. The baseline does not
  have a separate request-form-version aggregate, so its ID is also the form configuration ID.
- A custom field supplies the typed definition and validation metadata; a request-type field places
  it into one specific version; options belong to the custom field.

Client-supplied tenant IDs, role codes, audiences, project scopes, and service scopes are ignored or
rejected. Tenant and user identity come from `RequestContext`; catalogue permissions are evaluated
by the centralized authorization policy before tenant-filtered queries run. Authenticated users
with a recognized employee role receive the four read-only catalogue permissions; roleless JIT
users remain privilege-free. Request types additionally require `employee_visible_flag`;
unpublished or inactive configuration is not an audience mechanism.

## Publication and effective-version selection

At one server-generated UTC evaluation timestamp, a selectable version must be `PUBLISHED`, have a
non-null publication timestamp no later than evaluation, have no retirement timestamp, and satisfy
`effective_from <= evaluation < effective_to` when either bound exists. The request type, project,
tenant, and work type must also be active. Draft, under-review, retired, future-effective, and
expired versions are never selected.

Selection is deterministically ordered by effective start, version number, and immutable version
ID. If more than one published version is simultaneously effective, the API returns a non-sensitive
409 configuration conflict rather than choosing one silently. Published rows remain protected by
the baseline's immutability trigger.

The existing baseline protected the request-type version row but could not prevent later mutation
of its version-scoped layout or referenced custom fields/options. Alembic revision
`0005_catalogue_form_immutability` adds only the missing component triggers. It creates no catalogue
tables and has a complete downgrade; the physical baseline remains unchanged. Configuration must
therefore be assembled while its version is a draft and published only after fields and options are
complete.

## API

All endpoints require either OIDC bearer authentication or explicitly enabled local developer
identity:

```text
GET /api/v1/catalog/projects
GET /api/v1/catalog/projects/{project_id}
GET /api/v1/catalog/projects/{project_id}/services
GET /api/v1/catalog/projects/{project_id}/request-types
GET /api/v1/catalog/request-types/{request_type_id}
GET /api/v1/catalog/request-types/{request_type_id}/form
```

List endpoints accept bounded `limit` and `offset` parameters and use deterministic database
ordering. Cross-tenant, inactive, employee-hidden, and retired resources return no data. Unknown or
inaccessible IDs use non-disclosing 404 responses. An existing request type without one effective
published version returns a controlled configuration conflict.

The form response includes the stable request-type ID, immutable request-type/form version ID,
version number, effective period, project, work type, fields, validation data, conditional data,
and active options. Fields and options are returned in configured display order. The repository
loads options with the field query, so form rendering does not perform one query per field.

## Field and rule safety

The public field-type allowlist exactly follows the physical baseline:

`TEXT`, `LONG_TEXT`, `NUMBER`, `DATE`, `TIMESTAMP`, `BOOLEAN`, `SINGLE_SELECT`, `MULTI_SELECT`,
`USER`, `GROUP`, `SERVICE`, `MODULE`, `ASSET`, and `JSON_OBJECT`.

Validation metadata supports bounded length, numeric, item-count, and pattern values as inert data.
Conditional visibility/required-state data supports exactly one non-empty `all` or `any` group and
the operators `equals`, `not_equals`, `in`, `not_in`, `is_empty`, and `is_not_empty`. Unknown keys,
operators, malformed values, nested executable expressions, and template/script fields fail the
whole form as a safe configuration conflict. Task 3.1 exposes rules but does not execute them; the
future ticket-submission validator remains authoritative.

The baseline does not define an `APPLICATION_ENVIRONMENT` custom-field type or a project-to-service
node association. Application environments remain available through the existing registry for the
next ticket-submission task, and the current service tree is therefore tenant-wide after project
authorization. No duplicate tables or inferred relationships were added.

## Development fixtures and operations

`make seed` now loads both `database/development/identity_personas.sql` and the separate
`database/development/catalogue.sql`. Both targets refuse non-development environments. The
catalogue fixture contains deterministic, fictitious IT, ERP, HCM, SCM, BI, and SEC projects,
published request types, fields, options, and hierarchy nodes. It is not referenced by the
production baseline installer.

GNU Make is optional. From PowerShell, after the database is installed and migrated, the catalogue
fixture equivalent is:

```powershell
$env:APP_ENV = "development"
docker compose up -d --wait postgres
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d helpdesk -f /development/identity_personas.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d helpdesk -f /development/catalogue.sql
```

Run unit tests with `uv run pytest -m "not integration"` and PostgreSQL coverage with
`uv run pytest tests/integration/test_catalogue.py -m integration`. The integration suite validates
effective dating, overlap failure, field ordering, option filtering, cross-tenant isolation,
concurrent requests, and optional RLS.

## Observability, limitations, and next dependency

Bounded in-process metrics count catalogue/query operations, query duration, missing request types,
missing/overlapping versions, authorization failures, forms, and returned field counts. Structured
logs contain operation, duration, and row count only; normal reads do not create immutable audit
noise. Existing authorization denials continue to create security events. Direct PostgreSQL reads
are intentionally uncached in this first version, avoiding tenant/version cache invalidation risk.

Task 3.2 must reuse the returned request-type version ID when creating a ticket and must perform
authoritative field/default/conditional/environment validation. Drafts, submission, workflow,
routing, SLA, attachment, approval, notification, AI, and frontend behavior remain out of scope.
