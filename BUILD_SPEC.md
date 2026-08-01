# Fusion AI Helpdesk — Master Build Specification

**Document purpose:** This is the primary implementation specification for building a custom, Jira Service Management–style IT helpdesk using PostgreSQL, FastAPI, Next.js, pgvector, OpenAI or Anthropic Claude, and a governed knowledge repository containing approved Oracle Fusion documentation and company policies/procedures.

**Primary audience:** Engineers using Codex in Visual Studio Code, solution architects, database engineers, security reviewers, product owners, QA engineers, and DevOps engineers.

**Status:** Build-ready baseline  
**Target architecture:** Modular monolith with background workers  
**Database:** PostgreSQL 16+  
**Initial Oracle content targets:** Oracle Fusion Cloud Applications 26C and Oracle Fusion Data Intelligence 26.R2  
**Important:** Keep the Fusion Applications and Fusion Data Intelligence release streams separate.

---

## 1. How to use this document with Codex

Place this file at the root of the application repository as:

```text
BUILD_SPEC.md
```

Also extract the supplied PostgreSQL starter package into:

```text
database/baseline/fusion_helpdesk_postgres/
```

The expected baseline contains:

```text
sql/
  00_prerequisites.sql
  01_foundation.sql
  02_catalog_workflow.sql
  03_ticketing.sql
  04_routing_sla_approval.sql
  05_knowledge.sql
  06_ai_audit_integration.sql
  07_indexes_views_search.sql
  08_seed_reference.sql
  09_optional_rls.sql
  10_demo_bootstrap.sql
  11_demo_ticket.sql
  install_all.sql
  uninstall_all.sql

manifest/
  documentation_manifest_template.csv
  company_document_manifest_template.csv
  oracle_fusion_module_inventory.csv

scripts/
  load_manifest.py
  acquire_approved_documents.py
  register_local_documents.py
  requirements.txt
```

### 1.1 Codex working rules

When asking Codex to implement this application, always instruct it to:

1. Read `BUILD_SPEC.md` and the relevant source files before changing code.
2. Make small, reviewable changes.
3. Preserve the existing PostgreSQL baseline.
4. Use Alembic for all new schema changes after the initial baseline.
5. Never allow the browser, LLM, or generic SQL utility to update ticket tables directly.
6. Route ticket state changes through application services.
7. Add or update automated tests with every feature.
8. Run formatters, type checks, unit tests, and integration tests before declaring a task complete.
9. Do not implement automated crawling of Oracle websites unless the organization has recorded permission.
10. Do not hard-code LLM model names, secrets, tenant identifiers, role identifiers, support groups, priorities, or workflow status IDs.
11. Preserve immutable audit and ticket-event history.
12. Use UTC in the database and ISO 8601 timestamps in APIs.
13. Reject requests that fail authorization rather than relying on UI hiding.
14. Return source evidence for AI-generated answers.
15. Keep provider-specific OpenAI and Anthropic logic behind interfaces.

### 1.2 Recommended Codex task format

Use prompts structured like this:

```text
Read BUILD_SPEC.md and inspect the existing repository.

Implement only Milestone 1, Task 1.3: FastAPI application foundation.

Requirements:
- Follow the architecture and coding standards in BUILD_SPEC.md.
- Do not change the database baseline.
- Add tests.
- Run formatting, linting, type checking, and tests.
- Summarize files changed, decisions made, commands run, and remaining risks.
```

Do not ask Codex to “build the entire application” in one request. Complete one vertical slice or one well-defined task at a time.

---

## 2. Product vision

Build an enterprise IT service-management application in which:

- Employees can search for help through conversational AI.
- The employee agent first searches approved knowledge.
- The employee receives a source-grounded solution when suitable evidence exists.
- The employee can confirm whether the solution worked.
- If unresolved, the application creates a structured ticket.
- Tickets are assigned to support groups using deterministic routing rules.
- Analysts work from queues and a unified ticket workspace.
- Analysts receive AI assistance based on approved internal knowledge, historical fixes, Oracle documentation, related tickets, and permitted diagnostics.
- The complete ticket lifecycle, AI evidence, tool calls, approvals, SLA events, and user actions are auditable.
- Knowledge is versioned by product, release, module, audience, classification, approval status, and effective period.
- Company policy overrides generic operational guidance when the question is about company-specific behavior.
- Oracle documentation remains the authoritative external source for standard Oracle product behavior.

---

## 3. Initial scope

### 3.1 Included in the first production release

- Corporate single sign-on
- Employee service portal
- Service catalogue
- Configurable request forms
- Incident, service request, and access request workflows
- Ticket creation and unique ticket keys
- Support groups and analyst membership
- Deterministic routing
- Analyst queues
- Ticket details and activity timeline
- Public and internal comments
- Attachments
- Ticket participants
- First-response and resolution SLAs
- Business calendars
- Basic approvals
- Email notifications
- Knowledge document registration and versioning
- Document parsing and semantic chunking
- PostgreSQL full-text and pgvector search
- Employee helpdesk agent
- Analyst copilot
- Historical fix search
- Oracle documentation search
- AI evidence, feedback, and audit
- OAC-ready reporting extracts or views
- CI/CD, tests, monitoring, backup, and recovery

### 3.2 Deferred until the core is stable

- Full configuration-management database
- Advanced asset discovery
- Major incident command center
- On-call scheduling
- Automated production remediation
- Autonomous ticket closure
- Unreviewed AI-generated knowledge publication
- General-purpose SQL execution by an LLM
- Fully visual workflow designer
- Complex multi-company external customer service
- Mobile-native applications
- Microservice decomposition

---

## 4. Non-negotiable architecture principles

### 4.1 Modular monolith first

Implement one backend deployment with strongly separated modules. This reduces distributed-system complexity while allowing future extraction of services.

Backend modules:

```text
identity
catalog
tickets
workflows
routing
queues
sla
approvals
knowledge
ingestion
retrieval
ai
attachments
notifications
audit
integrations
reporting
```

Each module must have:

- API/router layer
- Application/service layer
- Domain models and rules
- Repository/data-access layer
- Pydantic schemas
- Tests

Avoid importing another module’s repositories directly. Call its public application service.

### 4.2 PostgreSQL is the system of record

The LLM is never the system of record. Ticket status, assignment, SLA state, approvals, document permissions, and audit history are controlled by PostgreSQL and the backend.

### 4.3 Tool-mediated AI

The LLM can request approved tools. The backend validates identity, authorization, arguments, and state before execution.

### 4.4 Deterministic routing

The LLM may classify an issue. The routing engine makes the final group assignment from configured rules.

### 4.5 Evidence-grounded answers

The employee agent and analyst copilot must not present unsupported factual resolutions. They must retain and expose evidence references.

### 4.6 Immutable history

Ticket events, security events, AI tool calls, AI evidence, and approval decisions are append-only from the application’s perspective.

### 4.7 Version everything important

Version:

- Workflows
- Prompt templates
- Knowledge documents
- Embedding models
- Retrieval configuration
- AI tools
- Company policies
- Oracle product releases
- API contracts

### 4.8 Security before convenience

Apply authorization before data retrieval and before tool execution. Do not rely on prompt instructions to protect documents or tickets.

---

## 5. Technology stack

| Layer                         | Technology                                                                    |
| ----------------------------- | ----------------------------------------------------------------------------- |
| Frontend                      | Next.js, React, TypeScript                                                    |
| UI components                 | Accessible component library plus project design system                       |
| Backend                       | Python 3.12+, FastAPI                                                         |
| ORM                           | SQLAlchemy 2.x                                                                |
| Validation                    | Pydantic 2.x                                                                  |
| Database migrations           | Alembic                                                                       |
| Operational database          | PostgreSQL 16+                                                                |
| Vector search                 | pgvector                                                                      |
| Full-text search              | PostgreSQL `tsvector`                                                         |
| Cache and locks               | Redis                                                                         |
| Background jobs               | Dramatiq, Celery, or ARQ; choose one                                          |
| Object storage                | MinIO locally; S3-compatible, OCI Object Storage, or Azure Blob in production |
| Authentication                | OIDC through Microsoft Entra ID or Oracle IAM                                 |
| LLM providers                 | OpenAI and Anthropic behind adapters                                          |
| Document parsing              | PyMuPDF, BeautifulSoup/selectolax, python-docx, openpyxl, python-pptx         |
| Malware scanning              | ClamAV or approved enterprise scanner                                         |
| API client generation         | OpenAPI-generated TypeScript client                                           |
| Unit/integration testing      | pytest                                                                        |
| Browser testing               | Playwright                                                                    |
| Frontend testing              | Vitest and React Testing Library                                              |
| Python formatting/linting     | Ruff                                                                          |
| Python type checking          | mypy or pyright                                                               |
| TypeScript formatting/linting | ESLint and Prettier                                                           |
| Observability                 | OpenTelemetry, structured logs, Prometheus-compatible metrics                 |
| Reporting                     | OAC against reporting views/schema                                            |
| Local orchestration           | Docker Compose                                                                |
| Production orchestration      | Kubernetes or managed container platform                                      |

---

## 6. Repository structure

Create this repository structure:

```text
fusion-ai-helpdesk/
├── BUILD_SPEC.md
├── README.md
├── .editorconfig
├── .gitignore
├── .env.example
├── Makefile
├── docker-compose.yml
├── pyproject.toml
├── package.json
├── pnpm-workspace.yaml
│
├── apps/
│   ├── api/
│   │   ├── alembic.ini
│   │   ├── alembic/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/
│   │   │   ├── db/
│   │   │   ├── identity/
│   │   │   ├── catalog/
│   │   │   ├── tickets/
│   │   │   ├── workflows/
│   │   │   ├── routing/
│   │   │   ├── queues/
│   │   │   ├── sla/
│   │   │   ├── approvals/
│   │   │   ├── attachments/
│   │   │   ├── knowledge/
│   │   │   ├── ingestion/
│   │   │   ├── retrieval/
│   │   │   ├── ai/
│   │   │   ├── notifications/
│   │   │   ├── audit/
│   │   │   ├── integrations/
│   │   │   └── reporting/
│   │   └── tests/
│   │
│   ├── worker/
│   │   ├── worker/
│   │   │   ├── main.py
│   │   │   ├── jobs/
│   │   │   └── consumers/
│   │   └── tests/
│   │
│   └── web/
│       ├── app/
│       │   ├── portal/
│       │   ├── agent/
│       │   ├── admin/
│       │   ├── api/
│       │   └── auth/
│       ├── components/
│       ├── features/
│       ├── lib/
│       ├── hooks/
│       ├── styles/
│       └── tests/
│
├── packages/
│   ├── api-client/
│   ├── ui/
│   ├── config/
│   └── test-fixtures/
│
├── database/
│   ├── baseline/
│   │   └── fusion_helpdesk_postgres/
│   ├── migrations/
│   ├── seed/
│   └── reporting/
│
├── ingestion/
│   ├── parsers/
│   ├── chunkers/
│   ├── classifiers/
│   ├── embeddings/
│   └── validation/
│
├── infrastructure/
│   ├── docker/
│   ├── kubernetes/
│   ├── terraform/
│   └── monitoring/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── operations/
│   ├── security/
│   └── decisions/
│
└── tests/
    ├── integration/
    ├── end_to_end/
    ├── performance/
    └── ai_evaluation/
```

---

## 7. Local development environment

### 7.1 Required software

- Docker Desktop or compatible Docker runtime
- Git
- Python 3.12+
- Node.js current LTS
- pnpm
- PostgreSQL client tools, including `psql`
- VS Code
- Codex extension or Codex CLI
- Optional: `make`

### 7.2 Docker Compose services

The first `docker-compose.yml` must define:

```text
postgres
redis
minio
minio-init
clamav
mailpit
api
worker
web
```

Recommended ports:

| Service       | Port |
| ------------- | ---: |
| Web           | 3000 |
| API           | 8000 |
| PostgreSQL    | 5432 |
| Redis         | 6379 |
| MinIO API     | 9000 |
| MinIO console | 9001 |
| Mailpit SMTP  | 1025 |
| Mailpit UI    | 8025 |
| ClamAV        | 3310 |

### 7.3 Environment variables

Create `.env.example` with placeholders only:

```dotenv
APP_ENV=development
APP_NAME=Fusion AI Helpdesk
APP_BASE_URL=http://localhost:3000
API_BASE_URL=http://localhost:8000

DATABASE_URL=postgresql+psycopg://helpdesk:helpdesk@postgres:5432/helpdesk
DATABASE_ADMIN_URL=postgresql://postgres:postgres@postgres:5432/helpdesk
REDIS_URL=redis://redis:6379/0

OBJECT_STORAGE_ENDPOINT=http://minio:9000
OBJECT_STORAGE_REGION=local
OBJECT_STORAGE_BUCKET=helpdesk
OBJECT_STORAGE_ACCESS_KEY=minio
OBJECT_STORAGE_SECRET_KEY=change-me
OBJECT_STORAGE_USE_SSL=false

OIDC_ISSUER_URL=
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
OIDC_AUDIENCE=
OIDC_REDIRECT_URI=http://localhost:3000/auth/callback

LLM_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_EMPLOYEE_AGENT_MODEL=
OPENAI_ANALYST_MODEL=
OPENAI_CLASSIFIER_MODEL=
OPENAI_EMBEDDING_MODEL=

ANTHROPIC_API_KEY=
ANTHROPIC_EMPLOYEE_AGENT_MODEL=
ANTHROPIC_ANALYST_MODEL=

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=
EMBEDDING_DIMENSION=1536

CLAMAV_HOST=clamav
CLAMAV_PORT=3310

SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_FROM=helpdesk@example.invalid

OTEL_EXPORTER_OTLP_ENDPOINT=
LOG_LEVEL=INFO

ORACLE_DOCUMENT_ACQUISITION_ENABLED=false
ORACLE_PERMISSION_REFERENCE=
```

Never commit real secrets.

### 7.4 Makefile targets

Implement at least:

```text
make bootstrap
make up
make down
make logs
make db-install
make db-demo
make db-reset
make migrate
make migration
make seed
make api
make worker
make web
make lint
make format
make typecheck
make test
make test-integration
make test-e2e
make openapi
make clean
```

---

## 8. PostgreSQL baseline

### 8.1 Baseline installation

The existing starter package is the physical baseline. Install it before Alembic takes ownership of later changes.

Run from its `sql` directory:

```bash
psql "$DATABASE_ADMIN_URL" -f install_all.sql
```

For local demonstration data:

```bash
psql "$DATABASE_ADMIN_URL" -f 10_demo_bootstrap.sql
psql "$DATABASE_ADMIN_URL" -f 11_demo_ticket.sql
```

Do not re-run the baseline installer as a production migration.

### 8.2 Existing database schemas

The baseline defines:

```text
identity
config
itsm
kb
ai
audit
integration
```

The application must preserve these logical boundaries.

### 8.3 Existing important tables

Identity:

```text
identity.tenant
identity.app_user
identity.business_unit
identity.role_definition
identity.user_role
identity.support_group
identity.support_group_member
```

Configuration:

```text
config.service_project
config.service_node
config.work_type
config.request_type
config.request_type_field
config.custom_field
config.custom_field_option
config.workflow
config.workflow_version
config.workflow_status
config.workflow_transition
config.routing_rule
config.queue_definition
config.business_calendar
config.calendar_working_period
config.calendar_exception
config.sla_definition
config.sla_goal
config.approval_definition
config.automation_rule
config.priority
config.category
config.channel
config.environment
config.resolution_code
```

Ticketing:

```text
itsm.ticket
itsm.ticket_event
itsm.assignment_history
itsm.ticket_comment
itsm.ticket_attachment
itsm.ticket_participant
itsm.ticket_custom_value
itsm.ticket_link
itsm.ticket_link_type
itsm.ticket_sla
itsm.ticket_sla_event
itsm.ticket_approval
itsm.ticket_approver
itsm.project_ticket_counter
```

Knowledge:

```text
kb.source
kb.product_node
kb.release
kb.document
kb.document_version
kb.document_chunk
kb.embedding_model
kb.chunk_embedding_1536
kb.document_permission
kb.ingestion_manifest_entry
kb.ingestion_run
kb.ingestion_run_item
```

AI and integration:

```text
ai.conversation
ai.message
ai.agent_run
ai.tool_call
ai.retrieval_evidence
ai.feedback
audit.security_event
integration.outbox_event
```

### 8.4 Migration strategy

After baseline installation:

1. Use Alembic for all application schema changes.
2. Configure Alembic to include all relevant PostgreSQL schemas.
3. Do not autogenerate destructive migrations without review.
4. Name migrations using a meaningful prefix and description.
5. Include downgrade logic unless explicitly impossible.
6. Run migrations in CI against a clean database.
7. Test migration from the previous tagged release.
8. Keep seed/reference changes separate from schema changes.

### 8.5 Database access roles

Create separate PostgreSQL roles:

```text
helpdesk_owner
helpdesk_migrator
helpdesk_app
helpdesk_worker
helpdesk_reporting
helpdesk_readonly
```

Guidelines:

- `helpdesk_owner`: owns schemas; no application login.
- `helpdesk_migrator`: used only by deployment migrations.
- `helpdesk_app`: API runtime permissions.
- `helpdesk_worker`: worker runtime permissions.
- `helpdesk_reporting`: read-only reporting views.
- `helpdesk_readonly`: controlled operational support access.

Do not grant runtime roles permission to delete or update immutable event/audit rows.

---

## 9. Identity and authorization

### 9.1 Authentication

Use OIDC authorization-code flow with PKCE.

In development, support a clearly isolated mock identity provider or developer login mode. Developer mode must never be enabled in production.

### 9.2 User synchronization

On successful login:

1. Validate OIDC token issuer, audience, signature, and expiry.
2. Read stable external subject identifier.
3. Locate or create `identity.app_user`.
4. Update non-authoritative profile fields.
5. Synchronize mapped roles and group membership where configured.
6. Load tenant, business unit, support groups, and effective permissions.
7. Issue an application session or use validated OIDC access tokens.

### 9.3 Application request context

Define:

```python
@dataclass(frozen=True)
class RequestContext:
    tenant_id: UUID
    user_id: UUID
    external_subject: str
    roles: frozenset[str]
    support_group_ids: frozenset[UUID]
    business_unit_id: UUID | None
    correlation_id: str
```

Every service method that accesses protected data must receive a `RequestContext`.

### 9.4 PostgreSQL transaction context

When row-level security is enabled, every transaction must execute:

```sql
SET LOCAL app.tenant_id = :tenant_id;
SET LOCAL app.user_id = :user_id;
```

Use a SQLAlchemy event hook or transaction helper. Add integration tests proving that context cannot leak between pooled connections.

### 9.5 Initial roles

```text
PLATFORM_ADMIN
PROJECT_ADMIN
SERVICE_OWNER
SUPPORT_MANAGER
AGENT
CUSTOMER
APPROVER
KNOWLEDGE_AUTHOR
KNOWLEDGE_APPROVER
AUDITOR
AI_ADMIN
REPORTING_USER
```

### 9.6 Authorization model

Check all applicable dimensions:

- Tenant
- Service project
- User role
- Support group
- Business unit
- Reporter/requested-for identity
- Ticket participant
- Ticket security classification
- Document permission
- Employee, analyst, or specialist audience
- Tool-specific permission
- Environment

Use policy classes or explicit authorization services. Avoid scattered role-name checks in routers.

---

## 10. Backend coding architecture

### 10.1 Layering

Each module should follow:

```text
router/API
    ↓
application service
    ↓
domain rules
    ↓
repository/unit of work
    ↓
PostgreSQL or external adapter
```

Rules:

- Routers handle HTTP concerns only.
- Services coordinate use cases and transactions.
- Domain objects enforce business invariants.
- Repositories contain query details.
- Provider adapters contain external API details.
- SQLAlchemy models are not returned directly by APIs.

### 10.2 Transaction management

Use a unit-of-work abstraction:

```python
class UnitOfWork(Protocol):
    tickets: TicketRepository
    events: TicketEventRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

One business operation should generally use one transaction.

### 10.3 Error model

Define domain exceptions:

```text
NotFoundError
AuthorizationError
ValidationError
ConflictError
InvalidTransitionError
ConcurrencyError
DuplicateSubmissionError
RateLimitError
ExternalDependencyError
KnowledgePermissionError
UnsupportedFileError
MalwareDetectedError
LLMProviderError
```

Map them to consistent API problem responses.

Recommended response:

```json
{
  "type": "https://helpdesk.example/errors/invalid-transition",
  "title": "Invalid workflow transition",
  "status": 409,
  "detail": "The ticket cannot move from Waiting for Customer to Closed.",
  "instance": "/api/v1/agent/tickets/ERP-104/transitions",
  "correlation_id": "01J...",
  "errors": [
    {
      "field": "transition_code",
      "message": "Transition is not available."
    }
  ]
}
```

---

## 11. Service catalogue and request forms

### 11.1 Concepts

- **Service project:** support domain such as ERP or BI.
- **Service node:** service/product/module hierarchy.
- **Work type:** internal type, such as incident.
- **Request type:** employee-facing catalogue entry.
- **Request form:** fields shown for a request type.
- **Custom field:** configurable typed field.

### 11.2 Initial service projects

```text
IT    Corporate IT Helpdesk
ERP   Oracle Fusion ERP Support
HCM   Oracle Fusion HCM Support
SCM   Oracle Fusion SCM Support
BI    Analytics and Reporting Support
SEC   Identity and Security
```

### 11.3 Initial request types

1. I cannot access an application.
2. Request access to Oracle Fusion.
3. Report an Oracle Fusion error.
4. Report an OTBI, BI Publisher, OAC, or FDI issue.
5. Request a new report or dashboard.
6. Report incorrect or missing data.
7. Report an integration failure.
8. Report a scheduled process failure.
9. Password or authentication problem.
10. Request software or equipment.
11. Request a production configuration change.
12. General IT question.

### 11.4 Form rendering

The frontend must retrieve form configuration from the API rather than hard-code forms.

API:

```http
GET /api/v1/catalog/request-types/{request_type_id}/form
```

Response:

```json
{
  "request_type_id": "uuid",
  "code": "REPORT_FUSION_ERROR",
  "name": "Report an Oracle Fusion error",
  "fields": [
    {
      "field_code": "summary",
      "data_type": "TEXT",
      "label": "Brief summary",
      "required": true,
      "display_order": 10
    },
    {
      "field_code": "environment",
      "data_type": "SINGLE_SELECT",
      "label": "Environment",
      "required": true,
      "options": [
        { "value": "PROD", "label": "Production" },
        { "value": "TEST", "label": "Test" }
      ],
      "display_order": 20
    }
  ]
}
```

Conditional fields must be evaluated by a safe rule interpreter, not arbitrary JavaScript.

---

## 12. Ticket lifecycle

### 12.1 Ticket creation

Employee flow:

```text
Select request type
→ load form
→ complete fields
→ optionally chat with agent
→ create draft
→ review normalized summary
→ confirm submission
→ create ticket
→ route ticket
→ start SLAs
→ emit notifications
→ return ticket key
```

### 12.2 Idempotency

Require an `Idempotency-Key` header for ticket submission and attachment finalization.

Store idempotency records with:

- Tenant
- User
- Endpoint
- Key
- Request hash
- Response code
- Response body or result reference
- Expiry

A repeated identical request returns the prior result. A repeated key with a different request hash returns conflict.

### 12.3 Ticket creation service

Pseudocode:

```python
async def submit_ticket(
    ctx: RequestContext,
    command: SubmitTicketCommand,
    idempotency_key: str,
) -> TicketResult:
    authorize_create_ticket(ctx, command.project_id)

    async with uow_factory(ctx) as uow:
        existing = await uow.idempotency.find(...)
        if existing:
            return existing.result

        form = await request_type_service.get_active_form(...)
        normalized = form_validator.validate_and_normalize(command.fields)

        ticket_number = await ticket_counter.next_number(
            project_id=command.project_id,
            for_update=True,
        )

        ticket = Ticket.create(
            key=f"{project.key}-{ticket_number}",
            ...
        )

        await uow.tickets.add(ticket)
        await uow.events.append(TICKET_CREATED, ...)
        await uow.outbox.add(ROUTE_TICKET, ...)
        await uow.outbox.add(START_SLA, ...)
        await uow.outbox.add(NOTIFY_TICKET_CREATED, ...)
        await uow.idempotency.store(...)

        await uow.commit()
        return TicketResult.from_domain(ticket)
```

### 12.4 Optimistic concurrency

All analyst updates must include `row_version`.

Example:

```http
PATCH /api/v1/agent/tickets/ERP-104
If-Match: "7"
```

On mismatch return `409 Conflict` with current version.

### 12.5 Comments

Comment visibility:

```text
PUBLIC
INTERNAL
SYSTEM
AI_GENERATED
```

Rules:

- Customers can add public comments only.
- Agents can add public or internal comments.
- System comments are immutable.
- AI drafts are not public until approved.
- Notification logic sends only public content to the customer.

### 12.6 Attachments

Attachment flow:

```text
Request upload URL
→ upload to quarantine bucket
→ finalize upload
→ virus scan
→ validate MIME and extension
→ move to protected bucket
→ create attachment record
→ publish event
```

Do not accept a client-supplied object URI as trusted.

Store:

- Original filename
- Generated object key
- Content type
- Size
- Checksum
- Scanner result
- Uploader
- Visibility
- Created timestamp

---

## 13. Workflow engine

### 13.1 Supported initial workflows

Incident:

```text
NEW
→ TRIAGE
→ IN_PROGRESS
→ WAITING_FOR_CUSTOMER
→ RESOLVED
→ CLOSED

IN_PROGRESS → WAITING_FOR_THIRD_PARTY
RESOLVED → REOPENED
REOPENED → IN_PROGRESS
```

Service request:

```text
SUBMITTED
→ AWAITING_APPROVAL
→ APPROVED
→ IN_FULFILMENT
→ COMPLETED
→ CLOSED

AWAITING_APPROVAL → REJECTED
```

Access request:

```text
SUBMITTED
→ MANAGER_APPROVAL
→ SECURITY_REVIEW
→ FULFILMENT
→ VALIDATION
→ COMPLETED
→ CLOSED

MANAGER_APPROVAL → REJECTED
SECURITY_REVIEW → REJECTED
```

### 13.2 Workflow transition service

Inputs:

- Ticket key
- Transition code
- Expected row version
- Field updates
- Comment
- Actor context

Execution:

1. Authorize access.
2. Lock ticket.
3. Validate row version.
4. Load immutable workflow version.
5. Confirm transition is active for current status.
6. Evaluate transition conditions.
7. Validate required fields.
8. Execute synchronous actions.
9. Update current ticket state.
10. Add ticket event.
11. Add SLA/outbox/notification events.
12. Commit.
13. Return new ticket representation.

### 13.3 Rule language

Use a restricted JSON expression format:

```json
{
  "all": [
    {
      "field": "resolution_code",
      "operator": "is_not_null"
    },
    {
      "field": "assignment_group_id",
      "operator": "is_not_null"
    }
  ]
}
```

Supported operators initially:

```text
equals
not_equals
in
not_in
is_null
is_not_null
contains
starts_with
greater_than
greater_than_or_equal
less_than
less_than_or_equal
```

Never evaluate Python code, SQL, JavaScript, Jinja expressions, or LLM-generated executable text.

### 13.4 Transition actions

Initial action types:

```text
SET_FIELD
SET_TIMESTAMP
CLEAR_FIELD
ADD_EVENT
CREATE_APPROVAL
START_SLA
PAUSE_SLA
RESUME_SLA
COMPLETE_SLA
SEND_NOTIFICATION
PUBLISH_OUTBOX_EVENT
ASSIGN_GROUP
ASSIGN_USER
```

---

## 14. Routing engine

### 14.1 Principle

AI classification produces structured suggestions. Routing rules remain deterministic and auditable.

### 14.2 Classification output

```json
{
  "service_code": "ORACLE_FUSION",
  "module_code": "ACCOUNTS_PAYABLE",
  "category_code": "INVOICE_VALIDATION",
  "work_type_code": "INCIDENT",
  "impact_code": "MEDIUM",
  "urgency_code": "MEDIUM",
  "confidence": 0.91,
  "reason": "The user reports an invoice validation hold."
}
```

### 14.3 Routing rule evaluation

Sort active rules by:

1. Emergency/security precedence
2. Rule priority
3. Specificity
4. Effective start date
5. Stable rule ID as final tie-breaker

Stop at the first matching terminal rule unless the rule configuration says to continue.

### 14.4 Fallback

Every project must have a configured fallback support group.

If AI classification confidence is below the configured threshold, route to triage.

### 14.5 Assignment methods

Initial methods:

```text
GROUP_ONLY
ROUND_ROBIN
LEAST_OPEN_TICKETS
LEAST_WEIGHTED_WORKLOAD
SKILL_BASED
NAMED_ASSIGNEE
MANUAL
```

Implement `GROUP_ONLY` and `ROUND_ROBIN` first.

### 14.6 Routing audit

Record:

- Rule evaluated
- Rule matched
- Input values
- Selected group
- Selected analyst
- Classifier version and confidence
- Fallback reason
- Timestamp

---

## 15. Queue engine

### 15.1 Queue model

A queue is a saved filter, selected columns, and sort order. It does not own tickets.

A ticket may appear in many queues.

### 15.2 Initial queues

```text
Unassigned
Assigned to me
My group
Critical incidents
Approaching first-response breach
Approaching resolution breach
Waiting for customer
Recently reopened
Oldest unresolved
Access requests awaiting approval
```

### 15.3 Queue filter language

Use the same restricted expression engine as routing.

Compile configuration into parameterized SQL.

Never accept user-authored SQL.

### 15.4 Pagination

Use cursor pagination for large queues. Stable sort should end with ticket ID.

Example cursor fields:

```text
priority_rank
sla_target_at
created_at
ticket_id
```

### 15.5 Queue API

```http
GET /api/v1/agent/queues
GET /api/v1/agent/queues/{queue_id}/tickets?cursor=...&limit=50
```

Return:

- Ticket key
- Summary
- Priority
- Status
- Reporter
- Assignment group
- Assignee
- Created date
- Updated date
- First-response SLA
- Resolution SLA

---

## 16. SLA engine

### 16.1 Initial SLA metrics

- Time to first response
- Time to resolution

Add later:

- Time to next response
- Time awaiting approval
- Time to fulfilment
- Time to customer update

### 16.2 SLA state

```text
PENDING
RUNNING
PAUSED
COMPLETED
BREACHED
CANCELLED
```

### 16.3 Business calendars

Support:

- Time zone
- Working days
- Multiple working periods per day
- Holidays
- One-off exceptions
- 24x7 calendars
- Release-specific or group-specific calendars

### 16.4 Event-driven processing

Outbox events:

```text
TICKET_CREATED
TICKET_STATUS_CHANGED
TICKET_PRIORITY_CHANGED
TICKET_RESOLVED
CUSTOMER_COMMENT_ADDED
AGENT_PUBLIC_RESPONSE_ADDED
```

Workers determine whether each SLA starts, pauses, resumes, stops, or changes goal.

### 16.5 SLA worker

Run a periodic job to:

- Find running SLA instances approaching warning threshold.
- Emit warning once.
- Mark breach at target.
- Update cached remaining time fields if used.
- Avoid duplicate warnings through unique event keys.

### 16.6 Correctness tests

Create calendar arithmetic tests for:

- Daylight-saving transitions
- Holidays
- Multiple working periods
- Start outside working hours
- Pause and resume
- Priority change
- Ticket reopen
- 24x7 calendars

---

## 17. Approval engine

### 17.1 Initial approval modes

```text
ANY_ONE_APPROVER
ALL_APPROVERS
MINIMUM_COUNT
SEQUENTIAL
MANAGER
GROUP
```

Implement `ANY_ONE_APPROVER`, `ALL_APPROVERS`, and `MANAGER` first.

### 17.2 Decision rules

- Approver must be authorized.
- Decision can be made once unless reset by workflow.
- Approval comments are retained.
- Rejection reason may be mandatory.
- Decision emits a ticket event and workflow continuation event.
- Delegation must be explicit and audited.

### 17.3 Approval API

```http
GET  /api/v1/my/approvals
POST /api/v1/approvals/{approval_id}/decisions
```

Payload:

```json
{
  "decision": "APPROVE",
  "comment": "Approved for the requested period.",
  "expected_version": 2
}
```

---

## 18. Notification service

### 18.1 Channels

Initial:

- Email
- In-app notifications

Later:

- Microsoft Teams
- Slack
- SMS for critical incidents

### 18.2 Templates

Version notification templates. Parameters must be escaped.

Events:

```text
TICKET_CREATED
TICKET_ASSIGNED
PUBLIC_COMMENT_ADDED
STATUS_CHANGED
APPROVAL_REQUESTED
APPROVAL_DECIDED
SLA_WARNING
SLA_BREACHED
TICKET_RESOLVED
TICKET_CLOSED
```

### 18.3 Delivery

Use outbox events and a worker. Store delivery attempts, status, provider ID, and error detail.

---

## 19. Knowledge source governance

### 19.1 Source types

```text
ORACLE_PUBLIC_DOCUMENTATION
COMPANY_POLICY
COMPANY_PROCEDURE
INTERNAL_KNOWLEDGE
HISTORICAL_RESOLUTION
```

### 19.2 Release conventions

Use:

```text
FUSION_APPLICATIONS / 26C
FUSION_DATA_INTELLIGENCE / 26.R2
```

Never store these as generic `26R`.

### 19.3 Oracle acquisition permission

The application must not enable automated Oracle-hosted acquisition unless:

- `ORACLE_DOCUMENT_ACQUISITION_ENABLED=true`
- An approved permission reference is present.
- The corresponding manifest entry is approved.
- The source and entry permit the selected acquisition method.

Do not create a general crawler. Use only explicitly approved URLs or manually supplied files.

### 19.4 Object storage

Store original documents unchanged.

Recommended object keys:

```text
knowledge/{tenant_or_global}/{source_code}/{document_id}/{version_id}/original/{filename}
knowledge/{tenant_or_global}/{source_code}/{document_id}/{version_id}/normalized/{filename}
```

Preserve:

- Canonical URL
- Source title
- Copyright notice
- File checksum
- Acquisition timestamp
- Source last-modified timestamp
- Permission reference
- Parser version
- Extraction output
- Validation results

---

## 20. Ingestion pipeline

### 20.1 States

```text
QUEUED
ACQUIRING
ACQUIRED
EXTRACTING
EXTRACTED
CHUNKING
CHUNKED
EMBEDDING
EMBEDDED
VALIDATING
PUBLISHED
SKIPPED_UNCHANGED
BLOCKED_PERMISSION
FAILED
```

### 20.2 Jobs

```text
acquire_manifest_entry
register_local_document
scan_document
extract_document
classify_document
chunk_document
generate_embeddings
validate_document
publish_document
retire_superseded_version
```

### 20.3 Idempotency

Use SHA-256 to detect unchanged files.

Do not create a new document version for an identical checksum.

### 20.4 Parsers

Implement a parser interface:

```python
class DocumentParser(Protocol):
    supported_types: set[str]

    async def parse(self, file: StoredFile) -> ParsedDocument: ...
```

Parsed output:

```python
@dataclass
class ParsedSection:
    heading_path: tuple[str, ...]
    text: str
    page_number: int | None
    anchor: str | None
    content_type: str
    table_markdown: str | None = None
```

### 20.5 Chunking

Chunk by semantic structure, not arbitrary bytes.

Targets:

- Approximately 300–800 tokens for normal content.
- Preserve one complete procedure where practical.
- Keep warnings with the steps they qualify.
- Keep table headers and rows together.
- Include document title and heading path in embedding input.
- Avoid excessive overlap.

### 20.6 Validation

Validation checks:

- Non-empty extraction
- Correct language
- Correct release
- Valid product/module
- Duplicate ratio
- Broken-character ratio
- Chunk count
- Average and maximum chunk size
- Table extraction quality
- Missing headings
- Embedding completeness
- Copyright preservation
- Canonical URL presence
- Permission status
- Document approval status

Only approved, current, valid document versions may be retrieved.

---

## 21. Retrieval service

### 21.1 Retrieval input

```python
@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    tenant_id: UUID
    user_id: UUID
    persona: Literal["EMPLOYEE", "ANALYST", "SPECIALIST"]
    product_family: str | None
    module_code: str | None
    release_family: str | None
    release_code: str | None
    environment_code: str | None
    max_results: int = 8
```

### 21.2 Hard authorization filters

Before scoring:

- Document active
- Version current
- Validation passed or warning
- Approval status approved
- Effective period valid
- Tenant/global visibility
- User/document permission
- Persona audience
- Security classification
- Product/module compatibility
- Release compatibility

### 21.3 Hybrid retrieval

Use:

1. PostgreSQL full-text search.
2. pgvector cosine similarity.
3. Exact error-code or identifier matching.
4. Metadata match boosts.
5. Source authority weighting.
6. Optional reranker.

The existing `kb.search_chunks_1536` is a starting point. Wrap it in a repository and enforce ACLs before exposing results.

### 21.4 Reciprocal rank fusion

Recommended first implementation:

```text
rrf_score = Σ 1 / (k + rank)
```

Combine full-text and vector result lists, then apply metadata boosts.

### 21.5 Evidence result

```json
{
  "chunk_id": "uuid",
  "document_id": "uuid",
  "document_version_id": "uuid",
  "title": "Resolve Invoice Validation Holds",
  "heading_path": "Invoice Validation > Validation Holds",
  "content": "...",
  "source_type": "ORACLE_PUBLIC_DOCUMENTATION",
  "release_family": "FUSION_APPLICATIONS",
  "release_code": "26C",
  "product": "Financials",
  "module": "Accounts Payable",
  "canonical_url": "...",
  "page_number": 123,
  "full_text_score": 0.77,
  "vector_score": 0.86,
  "final_score": 0.91
}
```

### 21.6 Source authority

Examples:

| Question                         | Preferred source                                            |
| -------------------------------- | ----------------------------------------------------------- |
| Company access approval          | Company policy                                              |
| Internal incident procedure      | Company procedure                                           |
| Standard Oracle feature behavior | Oracle exact-release documentation                          |
| Company-specific Oracle setup    | Approved internal procedure                                 |
| Known recurring production issue | Validated historical resolution                             |
| New Oracle release functionality | Oracle readiness/What’s New plus internal impact assessment |

---

## 22. LLM provider abstraction

### 22.1 Interface

```python
@dataclass
class ModelUsage:
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    cost_estimate: Decimal | None


@dataclass
class ToolRequest:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    text: str
    tool_requests: list[ToolRequest]
    usage: ModelUsage
    provider: str
    model: str
    finish_reason: str


class LLMProvider(Protocol):
    async def generate(
        self,
        *,
        instructions: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        metadata: dict[str, str],
    ) -> LLMResult: ...
```

Implement:

```text
OpenAIProvider
AnthropicProvider
FakeLLMProvider
```

`FakeLLMProvider` is mandatory for deterministic tests.

### 22.2 Provider selection

Configuration decides provider by agent/task:

```yaml
agents:
  employee_helpdesk:
    provider: openai
    model_env: OPENAI_EMPLOYEE_AGENT_MODEL

  analyst_copilot:
    provider: anthropic
    model_env: ANTHROPIC_ANALYST_MODEL

  ticket_classifier:
    provider: openai
    model_env: OPENAI_CLASSIFIER_MODEL
```

### 22.3 Provider resilience

Implement:

- Timeout
- Retry for retryable errors
- Circuit breaker
- Rate-limit handling
- Maximum tool iterations
- Token/cost limit
- Cancellation
- Fallback provider only when explicitly configured
- Structured logging without exposing sensitive prompts

---

## 23. AI tool framework

### 23.1 Tool definition

```python
class AgentTool(Protocol):
    name: str
    description: str
    input_model: type[BaseModel]

    async def authorize(
        self,
        ctx: RequestContext,
        input_data: BaseModel,
    ) -> None: ...

    async def execute(
        self,
        ctx: RequestContext,
        input_data: BaseModel,
    ) -> ToolResult: ...
```

### 23.2 Tool execution rules

For every tool call:

1. Store requested tool call.
2. Validate JSON against Pydantic schema.
3. Authorize using current user and agent persona.
4. Apply rate limits.
5. Execute through application service.
6. Redact sensitive output.
7. Store result, duration, and outcome.
8. Return tool result to model.
9. Stop after configured iteration limit.

### 23.3 Employee tools

```text
get_user_context
get_request_type_form
search_knowledge
search_known_errors
create_ticket_draft
submit_ticket
get_ticket_status
add_public_comment
list_my_tickets
```

### 23.4 Analyst tools

```text
get_ticket_context
search_internal_runbooks
search_historical_resolutions
search_oracle_documentation
get_related_tickets
get_sla_status
get_approved_diagnostics
draft_public_response
draft_resolution
create_problem_draft
create_change_draft
```

### 23.5 Prohibited tools

Do not provide:

- Arbitrary SQL
- Shell execution
- General browser access
- Direct database write
- Production change execution
- Password reset without verified workflow
- Unbounded external HTTP requests

---

## 24. Employee helpdesk agent

### 24.1 State machine

```text
NEW
→ COLLECTING_INFORMATION
→ CLASSIFIED
→ SEARCHING_KNOWLEDGE
→ SOLUTION_PROPOSED
→ AWAITING_RESOLUTION_CONFIRMATION

Resolved:
→ RESOLVED_WITHOUT_TICKET

Unresolved:
→ COLLECTING_TICKET_FIELDS
→ TICKET_DRAFT_READY
→ AWAITING_USER_CONFIRMATION
→ TICKET_SUBMITTED
```

### 24.2 Required behavior

The agent must:

- Identify user and permitted context.
- Ask only for information needed.
- Detect service, module, issue category, environment, impact, and urgency.
- Search approved knowledge before suggesting a resolution.
- Cite evidence.
- Clearly distinguish company policy, internal procedure, Oracle documentation, and historical fix.
- Ask whether the issue is resolved.
- Create a draft when unresolved or risky.
- Require user confirmation before ticket submission.
- Never invent a ticket number, assignment group, source, diagnostic result, or product behavior.

### 24.3 Escalation conditions

Immediately recommend/create ticket flow for:

- Security issue
- Suspected data breach
- Payroll issue
- Financial posting impact
- Production outage
- Multiple affected users
- Privileged access action
- Conflicting evidence
- No approved source
- Low retrieval confidence
- Failed prior solution
- Potential major incident

### 24.4 System instruction versioning

Store prompts as versioned configuration. Initial conceptual instruction:

```text
You are the internal IT helpdesk assistant.

Use only approved tools and retrieved evidence. Search authorized knowledge
before recommending a technical solution. Do not state unsupported product
behavior. Cite the evidence used. Prefer company policy for company-specific
rules and exact-release Oracle documentation for standard Oracle behavior.

When evidence is weak, conflicting, unavailable, security-sensitive, or the
action requires privileged access, collect the required information and prepare
a ticket draft. Never invent system status, ticket numbers, assignment groups,
documentation, diagnostics, or actions taken.

Before submitting a ticket, present the normalized ticket details and require
the employee to confirm.
```

### 24.5 Chat API

```http
POST /api/v1/assistant/conversations
POST /api/v1/assistant/conversations/{conversation_id}/messages
POST /api/v1/assistant/conversations/{conversation_id}/confirm-ticket
POST /api/v1/assistant/conversations/{conversation_id}/resolution-feedback
```

Support server-sent events for streaming.

---

## 25. Analyst copilot

### 25.1 Workspace outputs

- Ticket summary
- Timeline summary
- Missing information
- Suggested classification
- Similar resolved tickets
- Approved internal runbooks
- Exact-release Oracle documentation
- Suggested diagnostics
- Possible causes with confidence
- Draft public response
- Draft internal note
- Draft resolution
- Suggested ticket links
- Knowledge gap recommendation

### 25.2 Guardrails

- Do not expose other tickets unless the analyst is authorized.
- Redact personal data from historical examples when not needed.
- Clearly label inference.
- Require evidence for technical recommendations.
- Do not run production actions.
- Drafts remain editable.
- Closing, resolving, assigning, or changing priority remains an explicit analyst action.

### 25.3 Similar-ticket search

Index only eligible tickets:

- Resolved or closed
- Resolution validated or accepted
- No restricted data beyond analyst authorization
- Not marked as unsuitable for AI
- Current enough for the relevant product/release
- Linked root cause when available

Ranking signals:

```text
Semantic similarity
Same service/module
Same error code
Same environment
Same release
Resolution success
Low reopen rate
Recency
Knowledge validation
```

---

## 26. Historical resolutions

### 26.1 Publication workflow

A closed ticket does not automatically become trusted knowledge.

Flow:

```text
Closed ticket
→ resolution candidate
→ redact sensitive data
→ analyst/knowledge review
→ approve
→ publish to historical-resolution source
```

### 26.2 Stored content

- Symptom
- Environment
- Error identifiers
- Root cause
- Resolution steps
- Validation method
- Applicability
- Product/module/release
- Linked problem/change
- Source ticket
- Reviewer
- Approval date
- Expiry/review date

---

## 27. Background worker and outbox

### 27.1 Outbox pattern

Write business state and outbox records in the same transaction.

Worker processing must be:

- Idempotent
- Retryable
- Observable
- Dead-letter capable
- Correlation-ID aware

### 27.2 Initial event types

```text
ROUTE_TICKET
START_SLA
PROCESS_SLA_EVENT
SEND_NOTIFICATION
SCAN_ATTACHMENT
INDEX_TICKET
CLASSIFY_TICKET
INGEST_DOCUMENT
GENERATE_EMBEDDINGS
VALIDATE_DOCUMENT
PUBLISH_DOCUMENT
SYNC_IDENTITY
WRITE_REPORTING_EVENT
```

### 27.3 Worker locking

Use `FOR UPDATE SKIP LOCKED` or the selected job framework’s reliable locking.

### 27.4 Retry policy

- Exponential backoff with jitter.
- Maximum attempts by event type.
- Permanent validation failures move directly to failed/dead-letter.
- Store last error and next retry time.
- Admin UI can inspect and retry allowed failures.

---

## 28. Frontend architecture

### 28.1 Routes

Employee:

```text
/portal
/portal/catalog
/portal/catalog/[requestType]
/portal/chat
/portal/requests
/portal/requests/[ticketKey]
/portal/approvals
```

Analyst:

```text
/agent
/agent/queues
/agent/queues/[queueId]
/agent/tickets/[ticketKey]
/agent/knowledge
```

Administration:

```text
/admin
/admin/projects
/admin/services
/admin/request-types
/admin/forms
/admin/workflows
/admin/groups
/admin/routing
/admin/queues
/admin/slas
/admin/calendars
/admin/approvals
/admin/knowledge
/admin/ingestion
/admin/ai
/admin/audit
```

### 28.2 Employee portal pages

Dashboard:

- Start AI conversation
- Browse service catalogue
- Open requests
- Requests waiting for user
- Pending approvals
- Recent knowledge suggestions

Ticket page:

- Ticket key and status
- Summary and description
- Public activity timeline
- Public comments
- Attachments
- Participants
- SLA information suitable for customer display
- Add comment
- Reopen action when allowed

### 28.3 Analyst workspace

Three-column desktop layout:

```text
Queue navigation | Ticket workspace | Copilot/evidence panel
```

Ticket workspace tabs:

```text
Details
Activity
Attachments
Related tickets
SLAs
Approvals
AI evidence
Audit
```

### 28.4 State management

Use server state through a query library such as TanStack Query. Use local component state for transient UI only.

Do not maintain a second ticket truth in frontend global state.

### 28.5 Accessibility

Meet WCAG 2.2 AA where practical:

- Keyboard navigation
- Visible focus
- Labels and error descriptions
- Semantic landmarks
- Color-independent status indicators
- Screen-reader announcements for chat streaming
- Accessible tables and dialogs

---

## 29. API conventions

### 29.1 Versioning

Prefix with:

```text
/api/v1
```

### 29.2 Identifiers

Externally expose UUIDs and ticket keys. Avoid sequential internal IDs where they reveal scale or permit enumeration.

### 29.3 Dates

Use ISO 8601 UTC:

```text
2026-08-01T15:22:00Z
```

### 29.4 Pagination

Cursor pagination response:

```json
{
  "items": [],
  "next_cursor": "opaque",
  "has_more": false
}
```

### 29.5 Correlation IDs

Accept or generate `X-Correlation-ID`. Include it in logs, API errors, outbox records, and provider metadata.

### 29.6 Initial endpoint list

Employee:

```text
GET    /api/v1/catalog
GET    /api/v1/catalog/request-types/{id}
POST   /api/v1/ticket-drafts
POST   /api/v1/tickets
GET    /api/v1/my/tickets
GET    /api/v1/tickets/{ticketKey}
POST   /api/v1/tickets/{ticketKey}/comments
POST   /api/v1/tickets/{ticketKey}/attachments/presign
POST   /api/v1/tickets/{ticketKey}/attachments/finalize
GET    /api/v1/my/approvals
POST   /api/v1/approvals/{approvalId}/decisions
POST   /api/v1/assistant/conversations
POST   /api/v1/assistant/conversations/{id}/messages
```

Analyst:

```text
GET    /api/v1/agent/queues
GET    /api/v1/agent/queues/{queueId}/tickets
GET    /api/v1/agent/tickets/{ticketKey}
PATCH  /api/v1/agent/tickets/{ticketKey}
POST   /api/v1/agent/tickets/{ticketKey}/transitions
POST   /api/v1/agent/tickets/{ticketKey}/assignments
POST   /api/v1/agent/tickets/{ticketKey}/comments
POST   /api/v1/agent/tickets/{ticketKey}/links
POST   /api/v1/agent/tickets/{ticketKey}/copilot
```

Knowledge/admin:

```text
GET    /api/v1/knowledge/search
POST   /api/v1/admin/knowledge/sources
POST   /api/v1/admin/knowledge/manifest/import
POST   /api/v1/admin/knowledge/documents
POST   /api/v1/admin/knowledge/documents/{id}/versions
POST   /api/v1/admin/knowledge/documents/{id}/approve
POST   /api/v1/admin/knowledge/documents/{id}/retire
POST   /api/v1/admin/ingestion/runs
GET    /api/v1/admin/ingestion/runs/{id}
GET    /api/v1/admin/audit/events
```

---

## 30. Reporting and OAC

### 30.1 Do not run heavy analytics on operational tables

Create a reporting schema or separate reporting database.

### 30.2 Initial dimensions

```text
DIM_DATE
DIM_EMPLOYEE
DIM_ANALYST
DIM_SUPPORT_GROUP
DIM_SERVICE
DIM_MODULE
DIM_REQUEST_TYPE
DIM_WORK_TYPE
DIM_STATUS
DIM_PRIORITY
DIM_CHANNEL
DIM_KNOWLEDGE_DOCUMENT
DIM_AI_MODEL
```

### 30.3 Initial facts

```text
FACT_TICKET
FACT_TICKET_STATUS_HISTORY
FACT_TICKET_ASSIGNMENT
FACT_SLA
FACT_APPROVAL
FACT_AGENT_ACTIVITY
FACT_AI_INTERACTION
FACT_KNOWLEDGE_RETRIEVAL
FACT_TICKET_REOPEN
```

### 30.4 KPIs

- Ticket volume
- Open backlog
- Age distribution
- First-response time
- Resolution time
- SLA compliance
- Reassignment rate
- Reopen rate
- First-contact resolution
- AI containment
- Ticket deflection
- AI routing accuracy
- Knowledge success rate
- Analyst acceptance of AI suggestions
- Unsupported answer rate
- Retrieval with no suitable result
- Cost per AI interaction
- Mean time saved
- Knowledge gaps by module

---

## 31. Security requirements

### 31.1 Application security

- OIDC token validation
- CSRF protection where session cookies are used
- Secure, HTTP-only, same-site cookies
- CORS allowlist
- Rate limiting
- Input length limits
- Output encoding
- Strong file validation
- Dependency scanning
- Secret scanning
- Content Security Policy
- Secure headers
- Audit logs
- Least-privilege database roles

### 31.2 Attachment security

- Quarantine uploads
- Malware scan
- MIME sniffing
- Extension allowlist
- Size limits
- No direct public bucket access
- Short-lived signed download URLs
- Authorization on every download
- Optional image metadata stripping
- Retention policy

### 31.3 AI security

- Prompt injection detection and isolation
- Treat retrieved content as untrusted data
- Explicit tool allowlists
- Per-tool authorization
- Maximum tool iterations
- Maximum context size
- PII redaction
- Secret redaction
- Model output validation
- Evidence requirement
- No unrestricted web or SQL tools
- Provider data-processing review
- Tenant isolation
- AI kill switch
- Cost and rate limits

### 31.4 Logging restrictions

Do not log:

- Access tokens
- API keys
- Passwords
- Full sensitive documents
- Unredacted PII
- Private attachment contents
- Raw prompts containing secrets

Use structured fields and redacted summaries.

---

## 32. Observability

### 32.1 Logs

Structured JSON logs including:

```text
timestamp
level
service
environment
correlation_id
trace_id
tenant_id
user_id_hash
ticket_key
operation
duration_ms
outcome
error_code
```

### 32.2 Metrics

API:

- Request count
- Latency
- Error count
- Authentication failures
- Database pool utilization

Tickets:

- Creation rate
- Transition failure rate
- Routing fallback rate
- Queue query latency
- SLA processing lag

Knowledge:

- Ingestion throughput
- Parse failure rate
- Embedding failure rate
- Retrieval latency
- Empty-result rate

AI:

- Runs by agent/provider/model
- Token usage
- Cost estimate
- Tool calls
- Tool failures
- Unsupported-answer detection
- User feedback
- Analyst acceptance

Workers:

- Outbox backlog
- Oldest unprocessed event
- Retry count
- Dead-letter count

### 32.3 Tracing

Trace:

```text
HTTP request
→ application service
→ database queries
→ outbox
→ worker
→ retrieval
→ LLM call
→ tool execution
```

---

## 33. Testing strategy

### 33.1 Unit tests

Test:

- Domain rules
- Workflow conditions
- Routing rule matching
- Queue expressions
- SLA calendar arithmetic
- Approval logic
- Redaction
- Prompt-building
- Tool authorization
- Retrieval score fusion
- Parser/chunker behavior

### 33.2 Integration tests

Run against real PostgreSQL with pgvector and Redis.

Test:

- Baseline install
- Alembic upgrade/downgrade
- Ticket creation transaction
- Ticket key concurrency
- Optimistic locking
- Workflow transition
- Routing
- SLA event processing
- RLS isolation
- Outbox idempotency
- Knowledge ACL filtering
- Hybrid retrieval
- Attachment lifecycle

### 33.3 End-to-end tests

Playwright scenarios:

1. Employee logs in and creates ticket.
2. Ticket routes to expected group.
3. Analyst sees ticket in queue.
4. Analyst adds public comment.
5. Employee sees comment.
6. Analyst resolves ticket.
7. Employee reopens ticket.
8. Employee uses AI and receives cited answer.
9. Unresolved chat produces confirmed ticket.
10. Analyst copilot drafts response with evidence.

### 33.4 AI evaluation

Create a versioned evaluation dataset with:

- Question
- Persona
- Product/module/release
- Expected source type
- Required evidence
- Allowed answer
- Forbidden claims
- Expected escalation
- Expected classification
- Expected routing group

Metrics:

- Retrieval recall
- Evidence precision
- Citation correctness
- Groundedness
- Classification accuracy
- Routing recommendation accuracy
- Escalation correctness
- Unsupported claim rate
- PII leakage
- Prompt injection resistance

Do not promote prompt/retrieval changes without regression evaluation.

### 33.5 Performance tests

Initial targets, to be refined:

- Ticket list p95 under 500 ms for typical queues.
- Ticket details p95 under 500 ms excluding large attachments.
- Ticket creation p95 under 1 second excluding asynchronous processing.
- Knowledge retrieval p95 under 2 seconds before LLM generation.
- Employee agent first streamed response event under 2 seconds when provider permits.
- Support at least the agreed concurrent-user and ticket-volume target.

---

## 34. CI/CD

### 34.1 Pull-request pipeline

Run:

1. Secret scan
2. Dependency vulnerability scan
3. Python formatting/lint
4. Python type check
5. Frontend lint/type check
6. Unit tests
7. PostgreSQL integration tests
8. Migration validation
9. Build API image
10. Build worker image
11. Build web image
12. Playwright smoke tests
13. AI evaluation smoke subset

### 34.2 Deployment environments

```text
development
integration
test
preproduction
production
```

### 34.3 Deployment order

1. Backup/checkpoint.
2. Run backward-compatible database migrations.
3. Deploy API and workers.
4. Deploy frontend.
5. Run smoke tests.
6. Enable new feature flags.
7. Run post-deployment checks.
8. Monitor errors and rollback criteria.

### 34.4 Feature flags

Use flags for:

- Employee agent
- Analyst copilot
- Oracle documentation retrieval
- Automated document acquisition
- RLS
- New workflow versions
- New routing engine
- New embedding model
- New LLM provider/model

---

## 35. Development milestones

## Milestone 0 — Repository and local platform

Deliver:

- Repository structure
- Docker Compose
- PostgreSQL, Redis, MinIO, Mailpit, ClamAV
- `.env.example`
- Makefile
- CI skeleton
- Developer README

Acceptance:

- `make bootstrap` succeeds.
- `make up` starts all dependencies.
- Health endpoints show database, Redis, and object-storage status.
- No secrets are committed.

## Milestone 1 — Database baseline and FastAPI foundation

Deliver:

- Install baseline SQL
- SQLAlchemy async engine
- Unit of work
- Request context
- Error model
- Health endpoints
- Alembic baseline marker
- Integration-test fixtures

Acceptance:

- Clean database builds from baseline.
- API can query seeded tenant/project data.
- Transaction context is isolated between tests.
- CI runs database integration tests.

## Milestone 2 — Identity and authorization

Deliver:

- OIDC integration
- Developer identity mode
- User synchronization
- Role and support-group loading
- Authorization policies
- Optional RLS implementation and tests

Acceptance:

- Customer cannot read another customer’s private ticket.
- Analyst can read only permitted project/group tickets.
- Admin access is explicit.
- Pooled connection context cannot leak.

## Milestone 3 — Service catalogue and ticket vertical slice

Deliver:

- Catalogue APIs
- Dynamic request form
- Draft
- Submit ticket
- Ticket key
- Ticket details
- Public comment
- Basic portal and analyst page

Acceptance scenario:

```text
User logs in
→ selects “Report an Oracle Fusion issue”
→ completes form
→ confirms
→ ERP-1 is created
→ analyst sees it
→ analyst adds public comment
→ user sees comment
```

## Milestone 4 — Workflow, routing, queues, attachments

Deliver:

- Transition engine
- Deterministic routing
- Queue engine
- Assignment
- Optimistic locking
- Attachment quarantine and scan
- Activity timeline

Acceptance:

- Invalid transitions fail.
- Concurrent updates return conflict.
- Rule routes AP issue to configured AP group.
- Unassigned and assigned queues work.
- Infected attachment is rejected.

## Milestone 5 — SLA, approvals, notifications

Deliver:

- Business calendars
- First-response SLA
- Resolution SLA
- Warning/breach events
- Approval flow
- Email notifications
- In-app notifications

Acceptance:

- SLA pauses in waiting-for-customer status.
- Holiday calculation is correct.
- Approval decision advances workflow.
- Duplicate notifications are prevented.

## Milestone 6 — Knowledge administration and ingestion

Deliver:

- Source administration
- Manifest import
- Manual file upload
- Permission gate
- Object storage
- Parsing
- Chunking
- Embeddings
- Validation
- Publish/retire

Acceptance:

- Approved company document is searchable.
- Unapproved document is not searchable.
- Identical checksum is skipped.
- Oracle automated acquisition stays disabled without permission.
- Employee cannot retrieve analyst-only content.

## Milestone 7 — Hybrid retrieval

Deliver:

- Full-text search
- Vector search
- Fusion/reranking
- ACL enforcement
- Product/module/release filters
- Evidence API

Acceptance:

- Exact 26C AP query ranks applicable AP content.
- 26.R2 FDI content is not confused with Fusion Applications 26C.
- Unauthorized chunk never appears.
- Retrieval results include canonical evidence metadata.

## Milestone 8 — Employee helpdesk agent

Deliver:

- OpenAI/Anthropic adapters
- Tool framework
- Employee state machine
- Streaming chat
- Cited solutions
- Resolution feedback
- Ticket draft
- Confirmed submission

Acceptance:

- Agent searches before resolving.
- Unsupported question escalates.
- Ticket is not submitted without confirmation.
- Ticket key comes from backend.
- Tool authorization is enforced.

## Milestone 9 — Analyst copilot

Deliver:

- Ticket summary
- Similar resolutions
- Internal runbooks
- Oracle documentation
- Draft response
- Draft resolution
- Evidence panel
- Feedback

Acceptance:

- All technical recommendations have evidence.
- Analyst-only sources remain hidden from employees.
- Copilot cannot change ticket state by itself.
- Draft can be edited and posted by analyst.

## Milestone 10 — Reporting and production hardening

Deliver:

- OAC reporting model/feed
- Dashboards
- Performance testing
- Security testing
- AI evaluation suite
- Monitoring
- Backup/restore
- Operational runbooks
- Disaster recovery validation

Acceptance:

- Restore test succeeds.
- Critical alerts are configured.
- Security findings are resolved or accepted.
- AI regression thresholds pass.
- Production readiness review is signed off.

---

## 36. First Codex implementation tasks

Use these tasks in order.

### Task 0.1 — Initialize repository

```text
Read BUILD_SPEC.md.

Create the monorepo structure, root configuration files, .env.example,
Makefile, Docker Compose, and minimal READMEs. Configure Python with uv or
Poetry and frontend with pnpm. Do not implement business features yet.

Add health checks for PostgreSQL, Redis, MinIO, Mailpit, and ClamAV.
Add CI skeleton. Run all available checks.
```

### Task 0.2 — Add PostgreSQL baseline

```text
Read BUILD_SPEC.md and inspect database/baseline/fusion_helpdesk_postgres.

Add Makefile and Docker initialization commands to install the baseline SQL
against the local PostgreSQL container. Do not modify the baseline SQL unless a
verified defect prevents installation. Add a clean-database integration test
that installs the baseline and confirms expected schemas and tables.
```

### Task 1.1 — FastAPI foundation

```text
Implement the FastAPI application foundation:
- settings
- structured logging
- correlation ID middleware
- async SQLAlchemy engine
- unit of work
- request context placeholder
- problem-details error responses
- /health/live and /health/ready
- pytest configuration

Add tests and documentation.
```

### Task 1.2 — Alembic adoption

```text
Configure Alembic for the existing multi-schema PostgreSQL baseline. Create a
baseline marker without attempting to recreate existing tables. Add a sample
non-destructive migration and integration test for upgrade/downgrade.
```

### Task 2.1 — Developer identity and authorization

```text
Implement a development-only identity provider and RequestContext. Add role
and support-group loading from PostgreSQL. Implement authorization policy
classes and tests. Production OIDC will be added next.
```

### Task 3.1 — Service catalogue APIs

```text
Implement read-only service project, service node, request type, and dynamic
form APIs using the existing config tables. Add Pydantic response schemas,
repository methods, authorization, caching where appropriate, and tests.
```

### Task 3.2 — Ticket creation vertical slice

```text
Implement ticket draft and confirmed submission. Use an idempotency key,
project ticket counter, deterministic ticket key generation, ticket event, and
outbox records in one transaction. Add integration tests including concurrent
ticket-number allocation.
```

### Task 3.3 — Minimal portal and analyst UI

```text
Build the employee catalogue/request form and analyst ticket list/detail pages.
Generate the TypeScript client from OpenAPI. Do not hard-code request forms.
Add frontend tests and one Playwright vertical-slice test.
```

Continue milestone by milestone.

---

## 37. Definition of done for every task

A task is complete only when:

- Requirements are implemented.
- Authorization is applied.
- Error handling is defined.
- Database changes use Alembic.
- Unit tests are added.
- Integration tests are added where database behavior matters.
- API documentation is updated.
- Frontend states include loading, empty, error, and success.
- Logs and metrics are included for important operations.
- No secrets are committed.
- Format, lint, type check, and tests pass.
- Codex summarizes changed files and commands run.
- Any deferred risk is explicitly documented.

---

## 38. Coding standards

### Python

- Python 3.12+
- Type hints on public interfaces
- Async I/O for database and network operations
- Pydantic models for API/tool boundaries
- SQLAlchemy 2.x style
- Ruff formatting and linting
- Small functions with explicit names
- No hidden global mutable state
- Dependency injection through constructors/providers
- Domain exceptions rather than generic `Exception`
- UTC-aware datetimes only

### TypeScript

- Strict mode
- Generated API types
- No `any` without documented exception
- Functional React components
- Server components where appropriate
- Client components only when needed
- Accessible form controls
- Centralized API error mapping
- No duplicated backend business rules

### SQL

- Lowercase schema/table/column names
- Explicit constraints
- Foreign-key indexes where needed
- Parameterized statements
- No dynamic user SQL
- Transactional DDL through migrations
- Review query plans for high-volume queues/searches

### Git

- Small commits
- Conventional commit style
- One logical change per pull request
- No generated secrets or environment files
- Architecture decisions recorded under `docs/decisions`

---

## 39. Initial architecture decision records

Create:

```text
ADR-0001-modular-monolith.md
ADR-0002-postgresql-system-of-record.md
ADR-0003-pgvector-and-full-text-search.md
ADR-0004-tool-mediated-llm.md
ADR-0005-deterministic-routing.md
ADR-0006-versioned-workflows.md
ADR-0007-transactional-outbox.md
ADR-0008-object-storage-for-documents.md
ADR-0009-oracle-document-permission-gate.md
ADR-0010-provider-independent-llm-interface.md
```

Each ADR should state context, decision, alternatives, consequences, and status.

---

## 40. Production readiness checklist

### Platform

- [ ] Infrastructure as code reviewed
- [ ] Separate production secrets
- [ ] Database high availability
- [ ] Backup and point-in-time recovery
- [ ] Restore test completed
- [ ] Object-storage versioning and retention
- [ ] Redis availability plan
- [ ] Worker dead-letter handling
- [ ] Capacity/load test

### Security

- [ ] OIDC configured
- [ ] Least-privilege database roles
- [ ] RLS/security tests
- [ ] Penetration test
- [ ] Dependency vulnerabilities addressed
- [ ] Malware scanning
- [ ] PII handling reviewed
- [ ] LLM provider agreement reviewed
- [ ] Oracle documentation permission recorded
- [ ] Audit retention configured

### Application

- [ ] Workflow versions published
- [ ] Routing fallback configured
- [ ] SLA calendars validated
- [ ] Notification templates approved
- [ ] Support groups loaded
- [ ] Request forms approved
- [ ] Knowledge permissions validated
- [ ] AI kill switch tested
- [ ] Feature flags tested

### AI and knowledge

- [ ] Evaluation dataset approved
- [ ] Retrieval thresholds pass
- [ ] Citation accuracy passes
- [ ] Prompt injection tests pass
- [ ] Unsupported-claim rate within threshold
- [ ] Sensitive-data leakage tests pass
- [ ] Cost limits configured
- [ ] Model/provider fallback behavior tested
- [ ] Document version/release filtering tested

### Operations

- [ ] Runbooks complete
- [ ] Alerts routed
- [ ] Dashboard available
- [ ] On-call ownership assigned
- [ ] Incident process agreed
- [ ] Rollback process tested
- [ ] Data retention and deletion process tested

---

## 41. Immediate build order

Start with this exact sequence:

1. Extract the PostgreSQL starter package under `database/baseline`.
2. Commit this `BUILD_SPEC.md`.
3. Initialize repository and Docker Compose.
4. Install PostgreSQL baseline in local development.
5. Implement FastAPI health, settings, logging, DB engine, and unit of work.
6. Add Alembic baseline marker.
7. Add developer identity and authorization.
8. Build catalogue APIs.
9. Build one complete ticket vertical slice.
10. Build minimal employee and analyst interfaces.
11. Add workflow transitions.
12. Add deterministic routing and queues.
13. Add attachments.
14. Add SLA and approvals.
15. Add knowledge administration and ingestion.
16. Add hybrid retrieval.
17. Add employee agent.
18. Add analyst copilot.
19. Add reporting and production hardening.

The first success criterion is not “the chatbot works.” It is:

```text
An authenticated employee creates a configured request.
The backend creates ERP-1 exactly once.
The routing engine assigns the expected group.
An authorized analyst sees and works the ticket.
The employee sees public updates.
Every change is audited.
```

Once that vertical slice is dependable, add knowledge and AI capabilities as controlled application tools.
