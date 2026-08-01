# Production Architecture Addendum

## Purpose

This document extends BUILD_SPEC.md with production requirements identified
after Milestone 0, Task 0.1.

These requirements must be reviewed before the PostgreSQL baseline is installed.

## Implementation Rule

Implement foundational requirements before the first database baseline is
applied when delaying them would cause significant schema redesign, data
migration, security risk, or API incompatibility.

Deferred product features must be recorded in docs/PRODUCT_BACKLOG.md.

## Foundational Database Requirements

### 1. Configuration Versioning

Published configuration must be immutable and versioned.

The following configuration types require version control:

- Request forms
- Workflows
- Routing rules
- SLA policies
- Business calendars
- Approval definitions
- Queue definitions
- Notification templates
- AI prompts
- AI tool definitions
- Retrieval configurations

Each version must record:

- Version number
- Status
- Effective start and end dates
- Created by
- Approved by
- Change reason
- Previous version
- Publication timestamp
- Retirement timestamp

Tickets must retain references to the configuration versions used during
creation and processing.

### 2. API Idempotency

All externally initiated mutation operations must support idempotency.

Examples include:

- Ticket creation
- Comment creation
- Attachment registration
- Workflow transitions
- Approval decisions
- External webhook processing

The database must prevent duplicate processing using:

- Tenant
- Operation code
- Idempotency key
- Request hash

The original result must be returned when the same valid request is submitted
again.

### 3. Environment and Release Registry

The platform must maintain a registry of supported applications and
environments.

Each application environment must include:

- Application
- Environment name
- Instance or pod identifier
- Region
- Current release
- Planned next release
- Maintenance window
- Business owner
- Technical owner
- Primary support group
- Data classification
- Diagnostic endpoint references

Knowledge retrieval must use the release associated with the selected
environment.

Oracle Fusion Applications and Fusion Data Intelligence releases must remain
separate release families.

### 4. Priority Matrix

Final ticket priority must be calculated using deterministic impact and
urgency rules.

The LLM may recommend impact and urgency but must not directly assign the final
priority.

The database must support:

- Impact definitions
- Urgency definitions
- Priority definitions
- Impact and urgency matrix
- Effective dating
- Project-specific overrides
- Audit history

### 5. Email Correlation Metadata

The data model must support future inbound email processing.

Required metadata includes:

- External message ID
- External thread or conversation ID
- In-Reply-To header
- References header
- Sender address
- Recipient addresses
- Subject
- Received timestamp
- Processing status
- Processing error
- Linked ticket
- Original message storage location

The email gateway itself may be implemented in a later milestone.

### 6. Retention Policy Foundations

Retention policies must be configurable by record type and security
classification.

Policies must support:

- Tickets
- Comments
- Attachments
- AI conversations
- AI tool calls
- AI evidence
- Knowledge documents
- Audit events
- Integration messages
- Reporting data

Each policy must define:

- Retention duration
- Archive duration
- Deletion or anonymization action
- Legal-hold behavior
- Applicable tenant or project
- Effective dates
- Approval details

### 7. Attachment Security Metadata

Attachments must store security and processing metadata.

Required fields include:

- Original filename
- Storage object key
- Content type
- File size
- SHA-256 checksum
- Malware-scan status
- Malware-scan timestamp
- Quarantine status
- Encryption status
- Uploaded by
- Uploaded timestamp
- Retention policy
- Deleted timestamp
- Security classification

An attachment must not be available to users until authorization and security
checks are complete.

### 8. AI Feature Switches and Budgets

The platform must support database-controlled AI configuration.

Required controls include:

- Global AI enabled flag
- Per-agent enabled flag
- Provider
- Model
- Fallback provider and model
- Prompt version
- Tool-set version
- Retrieval configuration version
- Daily budget
- Monthly budget
- Maximum input tokens
- Maximum output tokens
- Maximum tool calls
- Maximum retrieved chunks
- Per-user rate limit

The ticketing platform must remain operational when AI is disabled or
unavailable.

### 9. Audit Requirements

Every material action must generate an immutable audit event.

Audit coverage must include:

- Authentication
- Authorization failures
- Ticket creation and updates
- Status changes
- Assignment changes
- Comments
- Attachments
- Approval decisions
- Configuration publication
- AI model usage
- AI tool calls
- Knowledge retrieval
- Administrative changes
- Data exports
- Data deletion or anonymization

Audit events must record:

- Tenant
- Actor
- Actor type
- Action
- Resource type
- Resource ID
- Previous values
- New values
- Correlation ID
- Request ID
- Source IP where available
- Timestamp

### 10. Database Operational Fields

Core operational tables must include consistent database-management fields.

Where appropriate, tables should include:

- Primary key
- Tenant ID
- Created at
- Created by
- Updated at
- Updated by
- Row version
- Active flag
- Effective start date
- Effective end date
- Deleted or retired timestamp
- Correlation ID
- Source system

High-volume event tables must be designed for future partitioning.

### 11. Service Ownership Hierarchy

The platform must represent business and technical service ownership.

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

Service ownership must influence:

- Routing
- SLA selection
- Escalation
- Knowledge filtering
- Reporting
- Major incident handling