# HelpdeskAgent UI Implementation Specification

## Goal

Reproduce the approved HelpdeskAgent concept as the visual target for the real
Next.js application.

The generated image is a concept, not a source design file. Some tiny labels and
values are illustrative. The implementation must match its structure, visual
hierarchy, density, colors, component language, and responsive behavior while
using real backend APIs and secure role-based data.

A practical target is a 95–98% structural and visual match. Literal
pixel-for-pixel reproduction is not possible from the concept image alone.

## Approved Reference

Store the image at:

```text
docs/design/HELPDESKAGENT_TARGET_UI.png
```

Store this specification at:

```text
docs/design/HELPDESKAGENT_UI_IMPLEMENTATION_SPEC.md
```

Use the image for visual decisions and use `BUILD_SPEC.md` for functional,
security, and architecture decisions.

## Required Workflow

```text
reference image
→ design tokens
→ shared components
→ screen specifications
→ real API integration
→ responsive behavior
→ Playwright screenshots
→ visual review and correction
```

Codex must not create each page independently or invent a different visual
style per feature.

## Design Tokens

Starting values inferred from the approved concept:

```css
:root {
  --background: #f6f8fc;
  --surface: #ffffff;
  --surface-subtle: #f8fafc;

  --sidebar: #0f1b2d;
  --sidebar-hover: #17263d;
  --primary: #2563eb;
  --primary-hover: #1d4ed8;
  --primary-soft: #eff6ff;
  --purple: #7c3aed;

  --text: #111827;
  --text-secondary: #4b5563;
  --text-muted: #6b7280;
  --border: #e5e7eb;

  --success: #16a34a;
  --success-soft: #ecfdf3;
  --warning: #f59e0b;
  --warning-soft: #fffbeb;
  --danger: #dc2626;
  --danger-soft: #fef2f2;
  --info: #0284c7;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --sidebar-width: 240px;
  --sidebar-collapsed-width: 72px;
  --topbar-height: 64px;
  --page-padding: 24px;
  --shadow-card: 0 1px 2px rgb(15 23 42 / 5%),
    0 4px 14px rgb(15 23 42 / 4%);
}
```

Typography:

- Font: Inter or the approved enterprise sans-serif equivalent
- Page title: 24–28 px, semibold
- Section title: 16–18 px, semibold
- KPI value: 24–32 px, semibold
- Body: 14 px
- Table and metadata: 12–13 px
- Buttons: 13–14 px, medium

Spacing system:

```text
4, 8, 12, 16, 20, 24, 32, 40 px
```

## Shared Application Shell

Implement once and reuse everywhere:

- dark left navigation
- product logo
- current user and role
- grouped navigation
- active-item highlight
- collapse control
- top search
- notifications
- settings/help controls
- permission-aware menu items
- responsive mobile drawer

Desktop:

```text
fixed sidebar + sticky top bar + scrolling content
```

Mobile:

```text
top bar + navigation drawer + single-column content
```

## Shared Components

Create reusable components before page-specific work:

### Navigation

- `AppSidebar`
- `SidebarItem`
- `TopBar`
- `GlobalSearch`
- `UserMenu`
- `Breadcrumbs`

### Layout and States

- `PageHeader`
- `Panel`
- `StatCard`
- `EmptyState`
- `ErrorState`
- `LoadingSkeleton`

### Status and Metadata

- `StatusBadge`
- `PriorityBadge`
- `SlaBadge`
- `TrendIndicator`
- `MetadataGrid`

### Tables and Lists

- `DataTable`
- `TableToolbar`
- `Pagination`
- `FilterChips`
- `TicketListItem`
- `QueueRow`

### Tickets

- `TicketHeader`
- `TicketTimeline`
- `TimelineEvent`
- `CommentComposer`
- `TicketSidePanel`
- `ParticipantCard`
- `AssignmentControl`
- `TransitionControl`

### Forms

- `DynamicRequestForm`
- typed field renderers
- `FormErrorSummary`
- `SubmissionReview`
- `ConfirmationDialog`

### Knowledge and AI

- `KnowledgeSearch`
- `KnowledgeArticleCard`
- `CitationCard`
- `EvidencePanel`
- `CopilotPanel`
- `StreamingMessage`

## Target Screens

### 1. Analyst Dashboard

Route:

```text
/analyst/dashboard
```

Composition:

```text
five KPI cards
tickets-by-status chart | SLA compliance | recent activity
my queue table | knowledge usage
```

### 2. Ticket Detail

Route:

```text
/analyst/tickets/[ticketKey]
```

Include:

- ticket key, status, summary
- project, request type, priority, reporter, created time
- edit, assign, transition, and overflow actions
- Details, Timeline, Conversations, Work Log, Attachments, Related tabs
- right-side ticket information and participants
- clearly separated public comments and internal notes

### 3. Employee Portal

Route:

```text
/portal
```

Include:

- help-search hero
- Browse Services and My Tickets
- popular service cards
- recent tickets
- knowledge suggestions
- AI assistant entry only when enabled

### 4. Dynamic Request Form

Route:

```text
/portal/requests/[requestTypeId]
```

Flow:

```text
form → validation → review → explicit confirmation → ticket key
```

The form must come from the exact immutable backend form version.

### 5. Analyst Queue

Route:

```text
/analyst/queues
```

Desktop layout:

```text
queue filters | ticket list | SLA summary
```

### 6. Knowledge Base

Routes:

```text
/knowledge
/knowledge/[articleId]
```

Include search, popular articles, filters, visibility rules, release metadata,
citations, and related articles.

### 7. Administration

Route:

```text
/admin
```

Include:

- users
- roles and permissions
- service catalogue
- workflows
- SLA policies
- business rules
- integrations
- system settings
- audit logs
- system KPIs and recent administrative activity

## Responsive Requirements

Desktop, 1280 px and above:

- full sidebar
- multi-column dashboard
- persistent ticket side panel
- dense tables

Tablet, 768–1279 px:

- collapsible sidebar
- two-column cards
- ticket side panel below main content

Mobile, below 768 px:

- navigation drawer
- single-column layout
- card-based ticket lists
- actions in menus or bottom sheets
- minimum 44 px interaction targets

## Accessibility

Require:

- WCAG AA contrast
- visible keyboard focus
- semantic headings
- labels for every field
- error summary linked to invalid inputs
- accessible icon-button names
- text alternatives for charts
- text as well as color for statuses
- reduced-motion support
- no hover-only functionality

## Demo Data

Use deterministic development fixtures, never production hard-coding.

Suggested personas:

- John Analyst
- Sarah Customer
- Maya Support Manager
- Alex Platform Admin

Suggested sample tickets:

- `ERP-2024-0056` — Oracle Fusion login issue
- `FIN-2024-0055` — Report not generating
- `HR-2024-0054` — Unable to access HR module
- `TECH-2024-0053` — Error in data upload
- `DB-2024-0052` — Database connection timeout

## Visual Acceptance Testing

Use Playwright screenshot tests at:

```text
1440 × 1024
1280 × 800
768 × 1024
390 × 844
```

Create screenshot tests for:

- analyst dashboard
- ticket detail
- employee portal
- dynamic request form
- analyst queue
- knowledge base
- admin dashboard

For stable screenshots:

- use deterministic fixtures
- freeze time
- disable animation
- wait for network idle
- use stable fonts
- mask only truly volatile fields
- store approved baselines in version control

Functional tests remain mandatory; screenshot tests do not replace them.

## Implementation Order

### Stage A — Design Foundation

1. Add the approved image and this specification.
2. Add design tokens.
3. Add typography and global layout.
4. Build the application shell.
5. Build shared cards, tables, badges, forms, and states.
6. Add Playwright screenshot infrastructure.

### Stage B — Current Employee Vertical Slice

1. Employee portal
2. Service catalogue
3. Dynamic request form
4. Draft review
5. Submission confirmation
6. Ticket success and detail
7. Minimal analyst list and detail
8. Public comments

### Stage C — Analyst Operations

1. Analyst dashboard
2. Queues
3. Workflow controls
4. Routing and assignment
5. Attachments
6. SLA
7. Approvals
8. Notifications

### Stage D — Knowledge and AI

1. Knowledge search
2. Article view
3. Evidence panel
4. Employee agent
5. Analyst copilot

### Stage E — Administration and Reporting

1. Admin shell
2. Identity and permissions views
3. Catalogue administration
4. Workflow and SLA configuration
5. Audit logs
6. Reporting
7. Production monitoring

## Security Rules for UI

The frontend must not:

- expose internal notes to customers
- expose analyst-only knowledge to employees
- display cross-tenant data
- trust role names supplied by the browser
- allow ticket submission without confirmation
- allow AI to mutate ticket state directly
- hard-code sensitive permissions
- bypass generated API contracts
- include tokens or credentials in logs

## Visual Definition of Done

A page is approved only when:

- layout silhouette matches the concept
- navigation position and density match
- spacing and typography are consistent
- cards, borders, and shadows use shared tokens
- tables and badges share one component language
- loading, empty, error, unauthorized, and conflict states exist
- mobile and tablet layouts are polished
- real API behavior works
- accessibility checks pass
- screenshot baselines are reviewed

## Codex Prompt

```text
Use docs/design/HELPDESKAGENT_TARGET_UI.png as the approved visual target and
docs/design/HELPDESKAGENT_UI_IMPLEMENTATION_SPEC.md as the UI implementation
contract.

Read BUILD_SPEC.md and the current master approval orchestrator first.

Do not begin with page-specific styling.

First inspect the existing Next.js app, generated OpenAPI client, authentication,
authorization, route structure, and frontend tests.

Build in this order:

1. design tokens
2. typography and global layout
3. reusable application shell
4. shared cards, tables, badges, forms, and state components
5. deterministic development fixtures
6. Playwright visual-test infrastructure

Then implement only the UI assigned to the current approved milestone.

For every screen:

- use real backend API contracts
- include loading, empty, error, unauthorized, and conflict states
- run Prettier, ESLint, TypeScript, Vitest, accessibility checks, and Playwright
- capture desktop, tablet, and mobile screenshots
- compare against the approved visual reference
- list remaining visible differences
- stop for human visual approval

Do not implement backend features early.
Do not use hard-coded production data.
Do not put direct role checks in page components.
Do not expose analyst-only data to customer pages.
Do not submit tickets without explicit confirmation.
Leave the task uncommitted until approval.
```
