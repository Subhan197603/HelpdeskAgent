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
| 11.5D | Knowledge administration                                        | `milestone-11-task-11.5d` | `d5eaeac44d9cd798dd18c379ea72d0f5be5a555d` |
| 11.5E | Read-only AI governance administration                          | `milestone-11-task-11.5e` | `dbd3cb537bf0a54099c81f1b27a579977774b7ab` |

Git ancestry places Task 11.5F before Task 11.5C. Preserve that history.

### Task 11.5D — Knowledge Administration

Status: `COMPLETED`.

The approved implementation provides tenant-scoped knowledge-administration
list and detail views, version and publication history, redacted ACL summaries,
bounded plaintext processing previews, and the existing approve, reject,
publish, and retire lifecycle operations behind dedicated permissions. Direct
document creation, revision editing, restore, category administration, and ACL
or audience mutation remain deferred. Migration `0023_knowledge_admin_index`
adds only the bounded GIN trigram title-search index and no runtime grant. Git
tag `milestone-11-task-11.5d` resolves to
`d5eaeac44d9cd798dd18c379ea72d0f5be5a555d`.

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

Git tag `milestone-11-task-11.5e` resolves to
`dbd3cb537bf0a54099c81f1b27a579977774b7ab`.

### Milestone 11 Closure State

Milestone 11 implementation, closure remediation, and final validation are
`COMPLETE`. Formal closure is `CLOSED` at the documentation-only governance
commit marked by the annotated tag `milestone-11-closure`.

The closure blockers were resolved and verified in order:

| Remediation | Result                                                          | Tag                           | Commit                                     |
| ----------- | --------------------------------------------------------------- | ----------------------------- | ------------------------------------------ |
| R1          | Nullable ticket impact and urgency compatibility                | `milestone-11-remediation-r1` | `1352d7357ec1523256058e1de8935407e9afbaec` |
| R2          | Direct AI hard-budget-stop enforcement evidence                 | `milestone-11-remediation-r2` | `e2a273f46e64ced901c741fc6a248aabf48ee170` |
| R3          | JavaScript advisory remediation and security-register alignment | `milestone-11-remediation-r3` | `9c50ad99c9b3befcd36fe8d5763ad045c290d241` |
| R4          | Gitleaks, Trivy, full CI, and approved Linux visual evidence    | `milestone-11-remediation-r4` | `ce1375edc574a3fc8befede0c5efc90861c69308` |

Final validation against the exact R4 state passed the complete backend,
frontend, PostgreSQL integration, Playwright, accessibility, visual, security,
build, and Compose gates. CI run `31696085111` passed all required jobs. The 88
approved Linux visual baselines remained byte-for-byte unchanged.

Three Moderate React Router advisories remain accepted under `SEC-2026-004`.
GitHub Actions Node.js 20 deprecation annotations and the accepted Starlette
TestClient deprecation warning are non-blocking follow-up items.

No Milestone 11 work has been promoted to the frozen production `main` or
`v1.0.0`, and no production deployment or image publication is authorized.
At Milestone 11 closure, Draft PR #1 remained open and unmerged and Milestone
12 was not authorized. The later roadmap amendment below defines Milestone 12
scope without authorizing implementation. Draft PR #1 remains open and
unmerged.

The completed bounded tasks preserve tenant isolation, authorization,
auditability, knowledge access controls, AI kill switches and budgets, tool
controls, and evidence requirements. Broader functionality remains subject to
the standard approval workflow:

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

## Post-v1 Milestone 13 — Governed Knowledge Operations

Status: `COMPLETE — FORMALLY CLOSED`.

Milestone 13 was a bounded, governed knowledge-operations milestone on
`develop`. All four tasks are complete, individually tagged
(`milestone-13-task-13.1` through `milestone-13-task-13.4`, final head
`176596b0112ca327e9e7bf3c799ee63baa761b3e`), each validated by an all-green
canonical CI run at its exact tag target. Formal closure is recorded by the
annotated tag `milestone-13-closure`. The development Alembic head is
`0030_corpus_publication`; the physical PostgreSQL baseline is unchanged, and
production remains frozen at v1.0.0 (`cc9d768`).

The roadmap amendment was authorized by
`APPROVE MILESTONE 13 GOVERNED KNOWLEDGE OPERATIONS ROADMAP AMENDMENT`.

Included capabilities:

- Approved-source inventory administration with an explicit refresh lifecycle
- Content-change detection over approved sources with removed-page and
  redirect handling
- Corpus validation with duplicate-document detection and near-duplicate chunk
  suppression
- Governed corpus-version publication and one-step audited rollback

Bounded task sequence:

1. **13.1 — Approved-source inventory and refresh lifecycle administration**
2. **13.2 — Content-change detection with removed-page and redirect handling**
3. **13.3 — Corpus validation with duplicate and near-duplicate detection**
4. **13.4 — Governed corpus publication and rollback**

The physical PostgreSQL baseline remains immutable. Any development migration
must follow `0026_analyst_ticket_watchlist`, remain task-specific, additive and
reversible, and preserve tenant isolation, least-privilege runtime grants, and
a single Alembic head.

The following Governed Knowledge Operations backlog items remain deferred and
outside Milestone 13:

- Governed knowledge authoring and administration designers
- New-release discovery
- Synonym and acronym management
- Exact error-code matching
- Zero-result analysis
- Stale-content penalties
- Advanced reranking
- Embedding-model migration

Zero-result analysis was later assigned to Milestone 14 by the ratified
roadmap amendment below.

## Post-v1 Milestone 14 — Retrieval Quality and Knowledge Gap Analytics

Status: `COMPLETE — FORMALLY CLOSED`.

Milestone 14 was a bounded retrieval-quality analytics milestone on
`develop`. All three tasks are complete, individually tagged
(`milestone-14-task-14.1` through `milestone-14-task-14.3`, final head
`9b70333426781793ae924da7561b54c244fbb535`), each validated by an all-green
canonical CI run at its exact tag target. Formal closure is recorded by the
annotated tag `milestone-14-closure`. The development Alembic head is
`0032_knowledge_gap_disposition`; retrieval behavior and the retrieval
regression suite are unchanged, the physical PostgreSQL baseline is
unchanged, and production remains frozen at v1.0.0 (`cc9d768`).

The roadmap amendment was authorized by
`APPROVE MILESTONE 14 ROADMAP AMENDMENT: RETRIEVAL QUALITY AND KNOWLEDGE GAP ANALYTICS`.

Included capabilities:

- Append-only, tenant-isolated retrieval query-event capture with bounded
  normalized query text and bounded retention
- Read-only zero-result and low-confidence analytics for knowledge
  administrators
- An audited knowledge-gap disposition workflow that references existing
  source governance without automating it

Bounded task sequence:

1. **14.1 — Retrieval query-event capture**
2. **14.2 — Zero-result and low-confidence analytics administration**
3. **14.3 — Knowledge-gap disposition and audit**

Milestone 14 never changes retrieval behavior: ranking, fusion, eligibility,
query rewriting or expansion, embeddings, reranking, the publication
lifecycle, and source governance are unchanged, and the retrieval regression
suite must remain green and unmodified.

The physical PostgreSQL baseline remains immutable. Any development migration
must follow `0030_corpus_publication`, remain task-specific, additive and
reversible, and preserve tenant isolation, least-privilege runtime grants, and
a single Alembic head.

The following backlog items remain deferred and outside Milestone 14:

- New-release discovery
- Synonym and acronym management
- Exact error-code matching
- Stale-content penalties
- Advanced reranking
- Embedding-model migration

## Future Milestone — Advanced AI Operations

- Mutable provider, model, policy, budget, and retrieval controls
- Active provider probing and manual circuit reset
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

## Post-v1 Milestone 12 — Analyst Personal Productivity

Status: `COMPLETE — FORMALLY CLOSED`.

Milestone 12 is a compact, non-destructive analyst productivity milestone on
`develop`. The roadmap amendment was authorized by
`APPROVE MILESTONE 12 ANALYST PRODUCTIVITY ROADMAP AMENDMENT`.

### Milestone 12 Closure State

All four tasks are complete, individually tagged, and remotely verified:
`milestone-12-task-12.1` (`2fb167b3`), `milestone-12-task-12.2` (`50229521`),
`milestone-12-task-12.3` (`a91ede6c`), and `milestone-12-task-12.4`
(`834eb762`). Two further approved bounded commits realigned exactly five
stale Milestone 11 analyst Linux visual baselines whose drift was caused by
approved Milestone 12 UI additions. Final canonical CI run `31939519533`
passed every job at the validated application commit
`3136c29f10d434a870b0b72f61d0d5de7d827c08`, including all Task 12.1–12.4
functional, accessibility, keyboard, and visual evidence. The development
Alembic head is `0026_analyst_ticket_watchlist`. Formal closure is recorded by
the documentation-only governance commit and annotated tag
`milestone-12-closure`.

Production `main` and `v1.0.0` remain frozen; no Milestone 12 work is promoted
to production. Draft PR #1 remains open and unmerged. Milestone 13 and all
future backlog work remain unauthorized until a separate plan and explicit
human approval.

Included capabilities:

- Personal saved ticket filters restricted to existing authorized queue inputs
- Personal canned responses inserted only into an editable comment draft
- Personal ticket watchlists without access, participant, assignment,
  notification, subscription, or outbox side effects
- Accessible keyboard accelerators for navigation, focus, selection, and help
  only

Bounded task sequence:

1. **12.1 — Personal saved ticket filters**
2. **12.2 — Personal canned responses**
3. **12.3 — Personal ticket watchlists**
4. **12.4 — Accessible keyboard accelerators**

The physical PostgreSQL baseline remains immutable. Any development migration
must follow `0023_knowledge_admin_index`, remain task-specific, additive and
reversible, and preserve tenant isolation, owner scoping, least-privilege
runtime grants, and a single Alembic head.

The following Analyst Productivity backlog items remain deferred and outside
Milestone 12:

- Ticket merge
- Duplicate-ticket management
- Bulk assignment
- Bulk transitions
- Work logs and time tracking
- Queue subscriptions and background notification behavior
- Shift handover
- Analyst availability
- Capacity and workload management
- Controlled export
- Shared or administrator-managed canned responses or saved filters
- Administrative queue editing, arbitrary sort shapes, and new filter languages

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

- Separately authorized production deployment and image publication
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
