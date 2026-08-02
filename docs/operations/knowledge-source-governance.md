# Knowledge source governance

Milestone 6, Task 6.1 adds the administrative registry and the permission gate only. It does not
download, upload, parse, store, or publish document content.

## Administrative API

The `/api/v1/admin/knowledge/sources` endpoints support tenant-visible listing, creation, complete
definition replacement, approval decisions, acquisition-authorization decisions, and acquisition
permission evaluation. Mutations require an `Idempotency-Key` and an expected row version where an
existing source is changed. A definition change resets approval to `DRAFT` and disables automated
access so that previously granted permission cannot silently authorize changed source details.

Knowledge authors may read, create, and update tenant sources. Knowledge approvers may read,
approve, and manage acquisition permission. Platform administrators hold both capabilities and are
the only role permitted to create or change global sources. Customers and other employees cannot
use source-administration endpoints. A user, or a member of an owning support group, cannot approve
that same source.

## Permission gate

External acquisition is denied unless every condition below is true:

- the source is `ACTIVE` and `APPROVED`;
- its method is an external acquisition method;
- the current immutable source version has an effective `APPROVED` authorization record;
- the authorization method matches the source method; and
- the source has not subsequently changed.

Oracle documentation has an additional deployment kill switch. It remains denied by default even
after source approval and an acquisition authorization. Enabling the switch records no permission
by itself; all ordinary gate conditions still apply.

The permission endpoint returns stable reason codes rather than attempting acquisition. Task 6.2
must call this server-side gate before performing any external I/O.

## Data and audit behavior

Sources retain tenant/global scope, audience (`EMPLOYEE`, `ANALYST`, `RESTRICTED`, or
`ADMINISTRATIVE`), owner, lifecycle, product/module/release metadata, and language. Acquisition
authorizations capture the exact source row version, method, canonical location, permission
reference, actor, and effective period. They are append-only. Source changes and authorization
decisions create audit events containing bounded governance summaries; credentials and document
content are not accepted or recorded.

The migration applies tenant-or-global row-level policies to both registry tables. The application
also scopes every query explicitly and enforces role permissions in the service layer.
