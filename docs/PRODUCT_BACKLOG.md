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

## Post-v1 Milestone 11 — User Experience and Administration

Milestone 11 is post-v1 development on `develop`. It is not part of the frozen
`v1.0.0` production release at
`cc9d76885e181230bd91f5b9bfd0605a9b23fb07`.

The following work is complete, as verified by its Git tag and commit:

| Task  | Capability                                                      | Tag                       | Commit                                     |
| ----- | --------------------------------------------------------------- | ------------------------- | ------------------------------------------ |
| 11.1  | Shared design system and application chrome                     | `milestone-11-task-11.1`  | `0396cccb0aba6ae0813eeb01f5604dcffe6193f6` |
| 11.2  | Analyst dashboard                                               | `milestone-11-task-11.2`  | `389ecfd6e50d3f8ea6b59094c4007eb80e13059b` |
| 11.3  | Ticket-detail alignment                                         | `milestone-11-task-11.3`  | `4a5f944d744231b46e657a51dd57989014a6855e` |
| 11.4  | Knowledge Base browsing and search                              | `milestone-11-task-11.4`  | `95d50937c706313d7879b9544ef57bfb8ed6cb2f` |
| 11.5A | Administration shell and overview                               | `milestone-11-task-11.5a` | `c40f536a703359ddb110190c43cc91800998fb28` |
| 11.5B | Read-only identity, role, queue, and ticket-view administration | `milestone-11-task-11.5b` | `a8556e9f67623891a0663c2b80dfa295f5f98b82` |
| 11.5F | Access-administration mutations                                 | `milestone-11-task-11.5f` | `b461fa86e7616ed95d3f04009e46255895569b97` |
| 11.5C | Workflow, SLA, calendar, and catalogue administration           | `milestone-11-task-11.5c` | `cc47d12fb716b3f4bd659931e19aabda8d1ea494` |

Git ancestry places Task 11.5F before Task 11.5C. Preserve that history.

### Task 11.5D — Knowledge Administration

Status: `NOT_STARTED_UNAUTHORIZED`.

This is a planning candidate for administration of the existing governed
knowledge lifecycle. Exact APIs, mutations, permissions, migrations,
acceptance criteria, and tests must be established in a separately approved
task plan. This entry does not authorize implementation.

### Task 11.5E — AI Governance

Status: `COMPLETED`.

The approved read-only implementation exposes secret-safe platform state,
provider/model aliases, process-local circuit observations, effective policies
and budgets, bounded tenant usage, and retrieval/embedding metadata behind
`AI_OVERSIGHT`. Runtime edits, provider probing, circuit reset, credentials,
deployment identifiers, and policy or budget mutations remain deferred. No
migration is required; development head remains
`0023_knowledge_admin_index`. Commit, tag, verification, and push were
authorized by `APPROVE MILESTONE 11 TASK 11.5E COMMIT`.

Both tasks must preserve tenant isolation, authorization, auditability,
knowledge access controls, AI kill switches and budgets, tool controls, and
evidence requirements. Each task must follow:

```text
PLAN
→ human approval
→ IMPLEMENT
→ full validation
→ human commit approval
→ COMMIT + TAG
→ verify
→ push
→ stop
```

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
