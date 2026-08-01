# Product Backlog

## Purpose

This document records deferred product capabilities that are not required for
the initial PostgreSQL baseline or the first ticketing vertical slice.

`BUILD_SPEC.md` is the authoritative implementation specification.

`docs/PRODUCTION_ARCHITECTURE_ADDENDUM.md` records foundational production
requirements.

This backlog controls implementation timing only. A backlog item must not
override architecture, security, database, or governance requirements in
`BUILD_SPEC.md`.

## Milestone 0, Task 0.2 — PostgreSQL Baseline

Implement only foundational structures that are expensive or unsafe to retrofit
after the first baseline installation:

- Add configuration-versioning foundations
- Add idempotency records and concurrency-safe processing state
- Add application, environment, and release registry
- Add deterministic impact, urgency, priority, and priority matrix
- Add email-correlation metadata foundations
- Add retention-policy and legal-hold foundations
- Add attachment-security metadata
- Add AI feature-switch, budget, and usage-ledger foundations
- Extend immutable audit structures
- Standardize operational fields where appropriate
- Extend the existing service hierarchy with ownership assignments
- Add baseline installation and integrity tests

Do not implement the email gateway, live LLM calls, document ingestion,
embeddings, CMDB, major incident management, problem management, or change
management during this task.

## Milestone 1 — Database and API Foundation

- Install the approved baseline
- Add the Alembic baseline marker
- Configure SQLAlchemy async database access
- Implement unit-of-work and transaction context
- Add application health checks
- Add database integration-test fixtures
- Validate tenant transaction context
- Add database role and privilege tests
- Add migration safety checks

## Milestone 3 — Ticket Vertical Slice

- Implement ticket-creation idempotency
- Apply deterministic priority calculation
- Capture request-form and workflow versions
- Record immutable ticket events
- Add public comments
- Add basic employee and analyst ticket views
- Add service, application, module, and environment selection

## Milestone 4 — Workflow, Routing, Queues, and Attachments

- Implement workflow transition service
- Implement deterministic routing
- Capture routing-rule versions in assignment history
- Implement analyst queues
- Add attachment quarantine
- Add malware scanning
- Add protected object-storage release
- Add signed and authorized attachment downloads
- Add attachment lifecycle audit

## Milestone 5 — SLA, Approvals, and Notifications

- Implement business calendars
- Implement first-response and resolution SLAs
- Capture SLA-goal and calendar versions
- Implement approval definitions and instances
- Capture approval-definition versions
- Implement versioned notification templates
- Add delivery attempts and failure handling
- Add in-app notifications

## Future Milestone — Email Channel

- Inbound mailbox integration
- New-ticket creation from email
- Reply correlation
- Provider and mailbox-specific message deduplication
- Raw MIME storage
- Email attachment extraction
- Mail-loop prevention
- Out-of-office suppression
- Delivery-failure processing
- Spoofing and sender authorization controls
- Public versus internal reply handling
- Email reconciliation reports

## Future Milestone — Knowledge Operations

- Oracle documentation refresh lifecycle
- Approved-source inventory
- New-release discovery
- Content-change detection
- Removed-page and redirect handling
- Corpus validation
- Corpus publication and rollback
- Synonym and acronym management
- Exact error-code matching
- Duplicate-document detection
- Near-duplicate chunk suppression
- Retrieval regression testing
- Zero-result analysis
- Stale-content penalties
- Advanced reranking
- Embedding-model migration

## Future Milestone — Advanced AI Operations

- AI budget dashboard
- Model and prompt approval workflow
- Prompt regression testing
- Retrieval regression testing
- Model-policy registry
- Automated configured fallback selection
- Provider circuit-breaker administration
- Agent usage analytics
- Cost allocation by tenant, project, and agent
- Conversation summarization and context management
- Embedding-model migration
- AI incident kill-switch workflow

## Future Milestone — Analyst Productivity

- Ticket merge
- Duplicate-ticket management
- Bulk assignment
- Bulk transitions
- Canned responses
- Work logs and time tracking
- Personal saved filters
- Watchlists
- Queue subscriptions
- Shift handover
- Analyst availability
- Capacity and workload management
- Controlled export
- Keyboard shortcuts

## Future Milestone — Extended ITSM

- Major incident management
- Major incident command workspace
- Problem management
- Known-error records
- Root-cause analysis
- Change management
- Change risk assessment
- Change approvals
- Change calendar
- Post-incident reviews
- Problem, incident, and change relationships

## Future Milestone — Assets and Services

- Full CMDB
- Asset inventory
- Configuration items
- Service dependency relationships
- Application dependency graph
- Discovery integration
- Asset ownership
- Asset lifecycle
- Warranty and vendor data
- Impact analysis based on dependencies

## Future Milestone — Production Operations

- PgBouncer and production pool sizing
- Primary and replica topology
- Point-in-time recovery
- Automated restore validation
- Database failover testing
- Table and index bloat monitoring
- Partitioning of high-volume event tables
- Archival automation
- Disaster recovery exercises
- Application SLO dashboards
- Capacity forecasting
- Software bill of materials
- Container image signing
- Deployment provenance and attestation

## Backlog Governance

For every backlog item:

- Assign a target milestone before implementation.
- Create or update an ADR when the item changes an architectural decision.
- Define security, privacy, and audit requirements.
- Define database migration impact.
- Define acceptance criteria and tests.
- Preserve backward compatibility unless an approved migration plan exists.
- Do not allow a deferred item to bypass foundational controls already defined
  in `BUILD_SPEC.md`.
