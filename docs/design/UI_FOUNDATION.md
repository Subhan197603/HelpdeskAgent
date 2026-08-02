# UI foundation

The HelpdeskAgent frontend uses the approved concept in
`HELPDESKAGENT_TARGET_UI.png` as its visual reference and
`HELPDESKAGENT_UI_IMPLEMENTATION_SPEC.md` as its implementation contract.
`BUILD_SPEC.md` remains authoritative for behavior, authorization, and data
visibility.

## Tokens and typography

All product tokens live in `apps/web/src/styles.css` as CSS custom properties.
They cover light-mode backgrounds and surfaces, the dark navigation shell,
semantic colors, text hierarchy, borders, shadows, radii, the 4–40 px spacing
scale, type sizes, shell dimensions, content width, motion, focus rings, and
z-index layers. Components must consume these variables instead of introducing
page-local color or spacing values.

The initial enterprise type stack is `Inter, Arial, "Segoe UI", sans-serif`.
It intentionally has no remote font request, making local operation and
Playwright rendering deterministic. Page titles are 24–28 px, section titles
are 17 px, body text is 14 px, and table/metadata text is 12–13 px.

## Component architecture

- `AppShell.tsx` owns the sidebar, top bar, user identity, active navigation,
  collapsed state, mobile drawer, and permission-aware navigation.
- `Layout.tsx`, `States.tsx`, and `Badges.tsx` contain layout, loading/empty/error,
  and semantic status primitives.
- `DataTable.tsx` contains typed table, toolbar, filters, sort, and pagination
  primitives.
- `Forms.tsx` contains labelled inputs, validation summaries, submission review,
  and a native focus-trapping confirmation dialog.
- `Tickets.tsx` contains list rows, headers, metadata, timelines, comments,
  participants, and side-panel presentation.
- `AttachmentUploader.tsx` presents quarantine and malware-scan state. It uses
  the generated API client for authorization/finalization and uses the returned
  pre-signed URL only for the object-storage transfer.

Feature pages continue to own API orchestration. Shared components do not embed
production data or backend business rules.

## Authorization and visibility

`GET /api/v1/me` returns the effective stable permission codes calculated by
the existing backend authorization service. The shell uses those codes for
navigation visibility and route affordances; it does not compare role display
names. Backend authorization remains mandatory and authoritative. Customer
pages never render the analyst visibility selector or internal timeline data.

## Responsive behavior

- At 1280 px and above, the sidebar is persistent, tables are dense, and the
  ticket information panel remains beside the timeline.
- From 768–1279 px, content columns reduce and the ticket information panel
  moves below the primary workspace.
- Below 768 px, the sidebar becomes a keyboard-operable drawer, ticket rows
  become cards, forms become single-column, and all controls retain a minimum
  44 px interaction target. Horizontal page scrolling is prohibited.

## Accessibility standard

New work targets WCAG 2.2 AA: semantic landmarks and headings, visible focus,
explicit labels/descriptions, linked error summaries, text in every status,
accessible table headers, named icon buttons, keyboard-operable navigation,
native modal focus behavior, no hover-only action, and reduced-motion support.
Playwright runs axe-core against the implemented employee and analyst screens.

## Visual tests and approval

Run the functional and visual browser suite with:

```powershell
pnpm test:e2e
```

Visual projects render at 1440×1024, 1280×800, 768×1024, and 390×844. Tests
freeze time, request reduced motion, wait for stable page content, enforce no
horizontal overflow, and permit a maximum changed-pixel ratio of 1.5%. Update
baselines only after confirming that the functional and accessibility checks
pass and manually comparing the result with the approved concept:

```powershell
pnpm exec playwright test tests/end_to_end/visual-foundation.spec.ts --update-snapshots
```

Commit approved files under `tests/end_to_end/visual-foundation.spec.ts-snapshots/`.
Do not mask stable product content or approve a baseline containing an error,
unauthorized response, unfinished loading state, or horizontal overflow.

## Known and intentional differences

- The concept combines several future dashboards in one image. This refinement
  includes only real catalogue, draft, ticket, workflow/routing queue, comment,
  and attachment capabilities completed through Milestone 4.
- SLA countdowns, approvals, notification-center behavior, knowledge, AI,
  reporting, and administration operations remain absent or visibly disabled.
- The shell uses simple repository-native SVG icons and deterministic system
  fonts rather than unlicensed concept-image assets.
- The analyst page is a queue and ticket workspace, not the future KPI/reporting
  dashboard. The right panel contains current ticket metadata, not SLA or AI
  evidence.
- Attachment history cannot be listed because no current customer-safe or
  analyst list endpoint exists. Newly uploaded files show their scan result in
  the current session.

New pages must extend these components and tokens. Any intentional deviation
from the reference must be documented here and covered by responsive and
accessibility tests.
