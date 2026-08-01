# Production Architecture Addendum

## Purpose

This document records production requirements identified after Milestone 0,
Task 0.1.

The authoritative implementation requirements are defined in `BUILD_SPEC.md`,
including Section 8.6 and the milestone definitions.

This addendum is a supporting architecture and governance document. Where this
document conflicts with `BUILD_SPEC.md`, `BUILD_SPEC.md` takes precedence.

These requirements must be reviewed before the PostgreSQL baseline is installed.

## Implementation Rule

Implement foundational requirements before the first database baseline is
applied when delaying them would cause significant schema redesign, data
migration, security risk, API incompatibility, or environment-isolation risk.

Do not implement every future production feature during Milestone 0, Task 0.2.

Deferred product features must be recorded in `docs/PRODUCT_BACKLOG.md` and
mapped to a later milestone.

## Foundational Database Requirements

### 1. Configuration Versioning

Published configuration must be immutable and versioned.

The following configuration types require version control:

- Request forms
- Workflows
- Routing rules
- SLA policies and goals
- Business calendars
- Approval definitions
- Queue definitions
- Notification templates
- AI prompts
- AI tool definitions
- AI agent configurations
- Retrieval configurations
- Embedding configurations

Each version must record:

- Version identifier or number
- Status
- Effective start and end dates
- Created by
- Created timestamp
- Approved by
- Approval timestamp
- Change reason
- Previous version
- Publication timestamp
- Retirement timestamp

Runtime records must retain the configuration versions relevant to their
operation:

- Ticket: request-form or request-type version and workflow version used at
  creation
- Assignment history: routing-rule version used
- Ticket SLA: SLA-goal and business-calendar versions used
- Approval instance: approval-definition version used
- Notification delivery: notification-template version used
- AI run: agent, prompt, tool-set, model-policy, and retrieval configuration
  versions used

Do not add every configuration version as a column on `itsm.ticket`. Store each
version reference on the runtime entity that actually used that configuration.

### 2. API Idempotency

All externally initiated mutation operations must support idempotency where a
duplicate request could create inconsistent or repeated business effects.

Examples include:

- Ticket creation
- Comment creation
- Attachment finalization
- Workflow transitions
- Approval decisions
- External webhook processing
- Inbound email processing
- Retryable integration operations

The database must prevent duplicate processing using:

- Tenant
- Operation code
- Idempotency key
- Request hash

The recommended uniqueness boundary is:

```text
tenant_id + operation_code + idempotency_key
```

The idempotency record must also support:

- Principal or integration identity
- Processing status
- Processing lease or lock expiration
- Result or resource reference
- Response status
- Safe response payload or response reference
- Created timestamp
- Completed timestamp
- Expiry timestamp
- Retryable failure state
- Conflict detection when the same key is used with a different request hash

Concurrent requests with the same valid idempotency key must not create
duplicate business records.

The original result must be returned when the same valid request is submitted
again.

### 3. Environment and Release Registry

The platform must maintain a registry of supported applications, application
environments, and deployed product releases.

Each application environment must include:

- Application
- Environment name
- Instance or pod identifier
- Region
- Current release
- Planned next release
- Release effective date
- Maintenance window
- Business owner
- Technical owner
- Primary support group
- Data classification
- Diagnostic endpoint references
- Active status

Knowledge retrieval must use the release associated with the selected
environment.

Oracle Fusion Applications and Oracle Fusion Data Intelligence releases must
remain separate release families.

Use separate concepts for:

- Operational application and environment releases
- Knowledge-document release applicability

`kb.release` remains the document-applicability release registry. Operational
application releases must be represented through the configuration or service
environment registry.

### 4. Priority Matrix

Final ticket priority must be calculated using deterministic impact and urgency
rules.

The LLM may recommend impact and urgency but must not directly assign the final
priority.

The database must support:

- Impact definitions
- Urgency definitions
- Priority definitions
- Impact and urgency matrix
- Effective dating
- Tenant or project-specific overrides
- Stable evaluation order
- Audit history

The backend priority service must calculate the final priority from the active
matrix.

Manual priority overrides must require authorization, reason capture, and an
audit event.

### 5. Email Correlation Metadata

The data model must support future inbound email processing.

Required metadata includes:

- Provider
- Mailbox or channel identifier
- External message ID
- External thread or conversation ID
- `In-Reply-To` header
- `References` header
- Sender address
- Recipient addresses
- CC recipients
- Subject
- Received timestamp
- Processing status
- Processing error
- Linked ticket
- Original message storage location
- Message checksum
- Created timestamp

Store raw MIME messages, large email bodies, and email attachments in protected
object storage.

Store only the object URI, checksum, normalized metadata, and searchable content
references in PostgreSQL.

Do not add every email field directly to `itsm.ticket`.

Prefer entities such as:

- `itsm.ticket_communication`
- `integration.email_message`
- `integration.email_recipient`

Scope external-message uniqueness by tenant, provider, and mailbox where
necessary.

The email gateway itself may be implemented in a later milestone.

### 6. Retention Policy Foundations

Retention policies must be configurable by record type, tenant, project,
security classification, and applicable jurisdiction where required.

Policies must support:

- Tickets
- Comments
- Attachments
- AI conversations
- AI messages
- AI runs
- AI tool calls
- AI evidence
- Knowledge documents
- Knowledge document versions
- Audit events
- Integration messages
- Reporting data
- Email messages
- Backups according to backup-retention policy

Each policy must define:

- Retention duration
- Archive duration
- Deletion, anonymization, or archive action
- Legal-hold behavior
- Applicable tenant or project
- Applicable record type
- Applicable security classification
- Effective dates
- Approval details
- Review date

Legal hold must override automated deletion and anonymization.

Use a separate legal-hold entity or legal-hold assignment model rather than a
single generic flag on every table.

Deletion or anonymization workflows must account for all relevant storage
locations:

- PostgreSQL
- Object storage
- Vector embeddings
- Full-text and external search indexes
- Redis or other caches
- Reporting stores
- LLM-provider retained data where contractually applicable
- Backups after the approved backup-retention period expires

### 7. Attachment Security Metadata

Attachments must store security and processing metadata.

Required fields include:

- Original filename
- Quarantine object key
- Protected object key
- Client-declared content type
- Detected MIME type
- File size
- SHA-256 checksum
- Malware-scan status
- Malware-scan timestamp
- Scanner engine
- Scanner version
- Threat name or detection details
- Quarantine status
- Quarantined timestamp
- Released timestamp
- Rejected timestamp
- Encryption status
- Uploaded by
- Uploaded timestamp
- Retention-policy reference
- Deleted timestamp
- Security classification
- Visibility
- Scan error details

An attachment must not be available to users until authorization and security
checks are complete.

Encryption keys, object-storage credentials, and signing secrets must never be
stored in PostgreSQL.

### 8. AI Feature Switches and Budgets

The platform must support database-controlled AI configuration.

Required scopes include:

- Global
- Tenant
- Environment
- Agent
- Use case

Required controls include:

- Global AI enabled flag
- Per-agent enabled flag
- Provider
- Model or deployment alias
- Fallback provider and model
- Prompt version
- Tool-set version
- Retrieval configuration version
- Embedding configuration version where applicable
- Daily budget
- Monthly budget
- Budget currency
- Warning threshold
- Hard-stop threshold
- Maximum input tokens
- Maximum output tokens
- Maximum tool calls
- Maximum retrieved chunks
- Maximum conversation context
- Per-user rate limit
- Effective dates
- Approval status

The platform must maintain a durable AI usage ledger or equivalent auditable
usage aggregation.

The ticketing platform must remain operational when AI is disabled, rate
limited, over budget, or unavailable.

Provider API keys and credentials must never be stored in AI configuration
tables. Credentials must be retrieved from the approved secret manager.

Circuit-breaker runtime state may be stored in Redis or another approved
runtime store, while durable configuration and audit records remain in
PostgreSQL.

### 9. Audit Requirements

Every material action must generate an immutable audit event.

Audit coverage must include:

- Authentication
- Authorization failures
- Ticket creation and updates
- Status changes
- Assignment changes
- Priority changes and overrides
- Comments
- Attachments
- Approval decisions
- Configuration publication
- AI model usage
- AI tool calls
- Knowledge retrieval
- Knowledge publication and retirement
- Administrative changes
- Data exports
- Data deletion or anonymization
- Legal-hold changes
- Integration and email processing outcomes

Audit events must record:

- Tenant
- Actor
- Actor type
- Action
- Resource type
- Resource ID
- Previous values where appropriate
- New values where appropriate
- Correlation ID
- Request ID
- Source channel
- Source IP where available
- Timestamp
- Outcome
- Failure reason where applicable

Audit, ticket-event, approval-decision, AI-evidence, and tool-call history is
append-only from the application perspective.

Runtime database roles must not have permission to update or delete immutable
history rows.

### 10. Database Operational Fields

Core operational tables must include consistent database-management fields
where appropriate.

Typical mutable operational tables should include:

- Primary key
- Tenant ID
- Created at
- Created by
- Updated at
- Updated by
- Row version
- Active flag where applicable
- Effective start date where applicable
- Effective end date where applicable
- Deleted or retired timestamp where applicable
- Correlation ID where applicable
- Source system where applicable

Do not add `updated_at`, `updated_by`, `active_flag`, `row_version`, or
soft-delete fields to append-only audit, event, decision, evidence, tool-call,
or immutable history rows unless there is a specific documented reason.

Use foreign keys, unique constraints, check constraints, and indexes to enforce
business integrity.

High-volume event tables must be designed for future time-based partitioning
without requiring partitioning during the initial MVP.

### 11. Service Ownership Hierarchy

The platform must represent business and technical service ownership.

Extend the existing `config.service_node` hierarchy rather than introducing a
second overlapping service hierarchy.

The hierarchy must support:

- Business service
- Technical service
- Application
- Module
- Business process
- Service owner
- Technical owner
- Support manager
- Primary support group
- Escalation group
- Vendor
- Criticality
- Support hours
- Recovery tier
- Data classification

Use effective-dated ownership-assignment records for people, groups, vendors,
and support responsibilities.

Service ownership must influence:

- Routing
- SLA selection
- Escalation
- Knowledge filtering
- Reporting
- Major incident handling

This is a service-ownership foundation and not a full CMDB.

A full CMDB, asset inventory, discovery integration, and dependency graph remain
deferred capabilities.

### 12. Baseline Acceptance Requirements

Before the first PostgreSQL baseline is accepted:

- Installation must succeed against a clean PostgreSQL 16+ database.
- Required schemas and extensions must exist.
- Required primary keys, foreign keys, unique constraints, and check constraints
  must be validated.
- Foundational configuration and reference data must load successfully.
- Demo data must remain optional and separate from the baseline.
- Oracle Fusion Applications and Fusion Data Intelligence release families must
  remain distinct.
- No production secrets or environment-specific identifiers may be hard-coded.
- The integration test suite must validate the foundational structures defined
  in this addendum and in `BUILD_SPEC.md`.
- Deferred product features must not be implemented as part of Task 0.2.
