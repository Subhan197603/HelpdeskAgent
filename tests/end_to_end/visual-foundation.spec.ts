import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const screenshotOptions = {
  animations: "disabled" as const,
  fullPage: true,
  maxDiffPixelRatio: 0.015,
};

const contentScreenshotOptions = {
  animations: "disabled" as const,
  maxDiffPixelRatio: 0.015,
};

async function expectAccessible(page: Page) {
  const result = await new AxeBuilder({ page })
    .exclude("[data-visual-only]")
    .analyze();
  expect(
    result.violations,
    result.violations.map((item) => `${item.id}: ${item.help}`).join("\n"),
  ).toEqual([]);
}

async function expectNoHorizontalScroll(page: Page) {
  const sizes = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(sizes.scroll).toBeLessThanOrEqual(sizes.client);
}

async function stabilizeEmployeePortalVisual(page: Page) {
  if (process.platform !== "linux" || page.viewportSize()?.width !== 768)
    return;

  await page.evaluate(async () => {
    await document.fonts.load('400 1rem "Inter Variable"');
    await document.fonts.ready;
  });
  await page.addStyleTag({
    content: `
      .portal-hero > p:not(.eyebrow) {
        margin-inline: auto;
        max-inline-size: 25rem;
      }
    `,
  });
  await expect
    .poll(() =>
      page
        .locator(".portal-hero > p:not(.eyebrow)")
        .evaluate((element) => element.getBoundingClientRect().height),
    )
    .toBeGreaterThan(30);
}

test("approved employee and analyst screens remain visually stable", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const recentTicketsRoute = "**/api/v1/my/tickets*";
  const stabilizeRecentTickets = page.viewportSize()?.width === 390;
  const openNavigation = async () => {
    const menu = page.getByRole("button", { name: "Open navigation" });
    if (await menu.isVisible()) await menu.click();
  };
  if (stabilizeRecentTickets) {
    await page.route(recentTicketsRoute, async (route) => {
      const ticket = (key: string) => ({
        created_at: "2026-08-02T10:00:00Z",
        creation_event_at: "2026-08-02T10:00:00Z",
        description:
          "Invoice validation fails with an unexpected application error.",
        environment_name: "Production",
        id: `00000000-0000-4000-8000-00000000000${key.slice(-1)}`,
        key,
        priority: "P4",
        project_code: "ERP",
        project_name: "Oracle Fusion ERP Support",
        public_comments: [],
        reporter_name: "Development Customer",
        reporter_user_id: "00000000-0000-4000-8000-000000000010",
        request_type_code: "ERP_ERROR",
        request_type_name: "Report an Oracle Fusion error",
        requested_for_name: null,
        requested_for_user_id: null,
        row_version: 1,
        service_name: null,
        status: "SUBMITTED",
        status_name: "Submitted",
        summary: "Oracle Fusion invoice error",
        updated_at: "2026-08-02T10:00:00Z",
        work_type: "REQUEST",
      });
      await route.fulfill({
        json: {
          items: [ticket("ERP-3"), ticket("ERP-2"), ticket("ERP-1")],
          limit: 50,
          next_cursor: null,
        },
      });
    });
  }
  await page.clock.install({ time: new Date("2026-08-02T10:30:00Z") });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();

  await expect(
    page.getByRole("heading", { name: "How can we help you?" }),
  ).toBeVisible();
  await stabilizeEmployeePortalVisual(page);
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("employee-portal.png", screenshotOptions);
  if (stabilizeRecentTickets) await page.unroute(recentTicketsRoute);

  await page
    .locator(".portal-hero")
    .getByRole("link", { name: "Browse services" })
    .click();
  await page
    .getByRole("tab", { name: /ERP.*Oracle Fusion ERP Support/ })
    .click();
  await page
    .getByRole("link", { name: /Report an Oracle Fusion error/ })
    .click();
  await expect(page.getByLabel("Brief summary")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "dynamic-request-form.png",
    screenshotOptions,
  );

  await page.getByLabel("Brief summary").fill("Oracle Fusion invoice error");
  await page
    .getByLabel("Detailed description")
    .fill("Invoice validation fails with an unexpected application error.");
  await page.getByLabel("Affected environment").selectOption("PROD");
  await page.getByRole("button", { name: "Review request" }).click();
  await expect(
    page.getByRole("heading", { name: "Review your request" }),
  ).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "submission-review.png",
    screenshotOptions,
  );

  await page.getByRole("button", { name: "Confirm and submit" }).click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Attachments" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "customer-ticket-detail.png",
    screenshotOptions,
  );

  // Knowledge base: landing, search, and article detail against seeded corpus.
  await openNavigation();
  await page.getByRole("link", { name: "Knowledge base" }).click();
  await expect(
    page.getByRole("heading", { name: "Knowledge Base" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Browse by type", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Oracle Fusion login issues" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Invoice validation runbook" }),
  ).toHaveCount(0);
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "knowledge-landing.png",
    screenshotOptions,
  );

  await page.getByLabel("Search knowledge articles").fill("password");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText(/Results for/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Oracle Fusion login issues" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Password reset guide" }),
  ).toBeVisible();
  await expect(page.locator("mark").first()).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "knowledge-search.png",
    screenshotOptions,
  );

  await page.getByRole("link", { name: "Oracle Fusion login issues" }).click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion login issues", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Article information" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "View original source" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "knowledge-article.png",
    screenshotOptions,
  );

  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  // Functional projects create tickets in the shared E2E database before the
  // visual projects. Keep this composition independent of project order while
  // retaining representative queue rows for responsive and accessibility QA.
  const queueRowLimitStyle = await page.addStyleTag({
    content:
      ".analyst-queues .ticket-list > :nth-child(n + 3) { display: none; }",
  });
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("analyst-queue.png", screenshotOptions);
  await queueRowLimitStyle.evaluate((style) => {
    style.parentNode?.removeChild(style);
  });

  await page.keyboard.press("Shift+/");
  await expect(
    page.getByRole("dialog", { name: "Keyboard shortcuts" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("shortcut-help.png", screenshotOptions);
  await page.keyboard.press("Escape");

  await openNavigation();
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Open Tickets", { exact: true })).toBeVisible();
  await expect(page.getByText("SLA Compliance (This Week)")).toBeVisible();
  await expect(page.getByText("Recent Activity")).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Open tickets by status/ }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-dashboard.png",
    screenshotOptions,
  );

  // Analyst knowledge: the confidential runbook is visible only here.
  await openNavigation();
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Knowledge Base" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Invoice validation runbook" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await openNavigation();
  await page.getByRole("link", { name: "My queues" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();

  await page
    .getByRole("link", { name: /Oracle Fusion invoice error/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("Assignment group")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-ticket-detail.png",
    screenshotOptions,
  );

  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(page.getByLabel("Comment visibility")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-ticket-activity.png",
    screenshotOptions,
  );

  await page.getByRole("tab", { name: "Attachments" }).click();
  await expect(page.getByText("No attachments yet.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Attachments", exact: true }),
  ).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.getByRole("tab", { name: "Participants" }).click();
  await expect(
    page.getByText("Participant management is not yet available"),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Work Log" }).click();
  await expect(
    page.getByText("Work log tracking arrives with a future milestone."),
  ).toBeVisible();
  await expectAccessible(page);

  // Server-truth actions: execute a real status transition last so earlier
  // screenshots stay deterministic.
  await page.getByRole("tab", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Change status" }).click();
  await page.getByRole("menuitem", { name: /In Progress|Start/ }).click();
  await expect(
    page.locator(".detail-header__badges").getByText(/in progress/i),
  ).toBeVisible();

  // Administration shell: platform administrator sees real counts, safe
  // system status, and the append-only audit history.
  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  await openNavigation();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Administration", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Active users")).toBeVisible();
  await expect(
    page.locator(".admin-card").getByRole("link", { name: "Audit logs" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-landing.png", screenshotOptions);

  await openNavigation();
  await page.locator('.sidebar-nav a[href="/admin/knowledge"]').click();
  await expect(
    page.getByRole("heading", { name: "Knowledge", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("4 tenant articles")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-knowledge.png", screenshotOptions);

  const sourcesRoute = "**/api/v1/admin/knowledge/sources*";
  await page.route(sourcesRoute, async (route) => {
    const source = (
      key: string,
      code: string,
      name: string,
      sourceType: string,
      overrides: Record<string, unknown>,
    ) => ({
      acquisition_method: "MANUAL_UPLOAD",
      approval_status: "APPROVED",
      approved_at: "2026-07-01T09:00:00Z",
      approved_by: null,
      audience_scope: "EMPLOYEE",
      automated_access_allowed: false,
      canonical_location: `https://kb.example.invalid/${key}`,
      code,
      created_at: "2026-07-01T09:00:00Z",
      effective_refresh_state: "CURRENT",
      id: `a0000000-0000-4000-8000-00000000000${key}`,
      language_code: "en",
      last_acquisition_at: null,
      last_acquisition_status: null,
      last_refresh_completed_at: null,
      last_refresh_requested_at: null,
      last_refresh_requested_by: null,
      module_code: null,
      module_node_id: null,
      name,
      owner_group_id: null,
      owner_user_id: null,
      permission_reference: null,
      product_code: null,
      product_node_id: null,
      publisher_name: null,
      refresh_due_at: null,
      refresh_state: "CURRENT",
      release_code: null,
      release_family: null,
      release_id: null,
      row_version: 1,
      scope: "TENANT",
      source_type: sourceType,
      status: "ACTIVE",
      updated_at: "2026-07-01T09:00:00Z",
      ...overrides,
    });
    await route.fulfill({
      json: {
        has_more: false,
        items: [
          source("1", "DEV_HANDBOOK", "IT Handbook", "INTERNAL_KNOWLEDGE", {
            effective_refresh_state: "REFRESH_DUE",
            last_refresh_completed_at: "2026-08-01T10:00:00Z",
            refresh_due_at: "2026-08-02T09:00:00Z",
            refresh_state: "REFRESH_DUE",
          }),
          source(
            "2",
            "ORACLE_FDI_DOCS",
            "Oracle Fusion Data Intelligence Documentation",
            "ORACLE_PUBLIC_DOCUMENTATION",
            { scope: "GLOBAL" },
          ),
          source(
            "3",
            "ORACLE_PUBLIC_DOCS",
            "Oracle Public Documentation",
            "ORACLE_PUBLIC_DOCUMENTATION",
            { scope: "GLOBAL" },
          ),
        ],
        offset: 0,
        total: 3,
      },
    });
  });
  await page.getByRole("tab", { name: "Sources" }).click();
  await expect(
    page.getByRole("heading", { name: "Knowledge sources", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("3 governed sources")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-knowledge-sources.png",
    screenshotOptions,
  );

  const changeReportRoute = "**/api/v1/admin/knowledge/sources/*/change-report";
  await page.route(changeReportRoute, async (route) => {
    const reportPage = (
      key: string,
      title: string,
      status: string,
      classification: string | null,
      overrides: Record<string, unknown>,
    ) => ({
      classification,
      completed_at: "2026-08-03T09:30:00Z",
      document_title: title,
      error_code: null,
      final_failure: false,
      item_id: `b0000000-0000-4000-8000-00000000000${key}`,
      manifest_key: `handbook-page-${key}`,
      observed_http_status: null,
      observed_sha256: null,
      previous_sha256:
        "6a5f0000000000000000000000000000000000000000000000000000000000aa",
      redirect_target_url: null,
      status,
      ...overrides,
    });
    await route.fulfill({
      json: {
        completed_at: "2026-08-03T09:30:00Z",
        created_at: "2026-08-03T09:00:00Z",
        pages: [
          reportPage("1", "Getting started", "SKIPPED_UNCHANGED", "UNCHANGED", {
            observed_sha256:
              "6a5f0000000000000000000000000000000000000000000000000000000000aa",
          }),
          reportPage("2", "Device policies", "ACQUIRED", "CHANGED", {
            observed_sha256:
              "9c1e0000000000000000000000000000000000000000000000000000000000bb",
          }),
          reportPage("3", "Legacy VPN guide", "SKIPPED_REMOVED", "REMOVED", {
            observed_http_status: 404,
          }),
          reportPage(
            "4",
            "Password portal",
            "SKIPPED_REDIRECTED",
            "REDIRECTED",
            {
              observed_http_status: 301,
              redirect_target_url:
                "https://kb.example.invalid/handbook/password-portal-v2",
            },
          ),
        ],
        requested_by: null,
        run_id: "c0000000-0000-4000-8000-000000000001",
        run_status: "COMPLETED",
        source_id: "a0000000-0000-4000-8000-000000000001",
        summary: {
          changed: 1,
          failed: 0,
          redirected: 1,
          removed: 1,
          unchanged: 1,
        },
        total_items: 4,
      },
    });
  });
  await page
    .getByRole("row", { name: /DEV_HANDBOOK/ })
    .getByRole("button", { name: "View changes" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Change report — DEV_HANDBOOK" }),
  ).toBeVisible();
  await expect(page.getByText("1 unchanged · 1 changed")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-knowledge-source-changes.png",
    screenshotOptions,
  );
  await page.getByRole("button", { name: "Close report" }).click();
  await page.unroute(changeReportRoute);
  await page.unroute(sourcesRoute);

  const corpusValidationRoute =
    "**/api/v1/admin/knowledge/corpus-validations/latest";
  await page.route(corpusValidationRoute, async (route) => {
    const finding = (
      key: string,
      findingType: string,
      overrides: Record<string, unknown>,
    ) => ({
      chunk_id: null,
      counterpart_chunk_id: null,
      counterpart_document_id: null,
      counterpart_document_title: null,
      document_id: `d0000000-0000-4000-8000-00000000000${key}`,
      document_title: `Handbook page ${key}`,
      document_version_id: null,
      duplicate_group_key: null,
      evidence: {},
      finding_type: findingType,
      id: `e0000000-0000-4000-8000-00000000000${key}`,
      similarity_score: null,
      suppression_flagged: false,
      ...overrides,
    });
    await route.fulfill({
      json: {
        chunk_count: 42,
        completed_at: "2026-08-05T09:30:00Z",
        document_count: 12,
        findings: [
          finding("1", "STRUCTURAL_DEFECT", {}),
          finding("2", "EMPTY_CHUNK", {
            chunk_id: "f0000000-0000-4000-8000-000000000002",
          }),
          finding("3", "DUPLICATE_DOCUMENT", {
            counterpart_document_id: "d0000000-0000-4000-8000-000000000004",
            counterpart_document_title: "Handbook page 4",
            duplicate_group_key:
              "6a5f0000000000000000000000000000000000000000000000000000000000aa",
          }),
          finding("5", "NEAR_DUPLICATE_CHUNK", {
            chunk_id: "f0000000-0000-4000-8000-000000000005",
            counterpart_chunk_id: "f0000000-0000-4000-8000-000000000006",
            counterpart_document_id: "d0000000-0000-4000-8000-000000000006",
            counterpart_document_title: "Handbook page 6",
            similarity_score: 0.9821,
            suppression_flagged: true,
          }),
        ],
        replayed: false,
        requested_by: null,
        run_id: "c1000000-0000-4000-8000-000000000001",
        similarity_threshold: 0.95,
        started_at: "2026-08-05T09:00:00Z",
        status: "COMPLETED",
        summary: {
          duplicate_documents: 1,
          empty_chunks: 1,
          near_duplicate_chunks: 1,
          structural_defects: 1,
        },
        truncated: false,
      },
    });
  });
  await page.getByRole("tab", { name: "Validation" }).click();
  await expect(
    page.getByRole("heading", { name: "Corpus validation", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("12 documents · 42 chunks")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-knowledge-validation.png",
    screenshotOptions,
  );
  await page.unroute(corpusValidationRoute);

  const corpusPublicationActiveRoute =
    "**/api/v1/admin/knowledge/corpus-publications/active";
  const corpusPublicationHistoryRoute =
    "**/api/v1/admin/knowledge/corpus-publications";
  const publishedCorpusVersion = {
    id: "c2000000-0000-4000-8000-000000000001",
    version_number: 2,
    validation_run_id: "c1000000-0000-4000-8000-000000000001",
    published_by: "22000000-0000-4000-8000-000000000001",
    published_at: "2026-08-05T10:00:00Z",
    document_count: 12,
    chunk_count: 42,
    suppressed_chunk_count: 1,
    active: true,
    replayed: false,
  };
  const priorCorpusVersion = {
    ...publishedCorpusVersion,
    id: "c2000000-0000-4000-8000-000000000002",
    version_number: 1,
    suppressed_chunk_count: 0,
    active: false,
  };
  await page.route(corpusPublicationActiveRoute, async (route) => {
    await route.fulfill({
      json: {
        active_version: publishedCorpusVersion,
        readiness: {
          publishable: true,
          blockers: [],
          validation_run_id: "c1000000-0000-4000-8000-000000000001",
          suppression_flagged_chunks: 1,
        },
      },
    });
  });
  await page.route(corpusPublicationHistoryRoute, async (route) => {
    await route.fulfill({
      json: {
        versions: [publishedCorpusVersion, priorCorpusVersion],
        events: [
          {
            id: "c3000000-0000-4000-8000-000000000002",
            action: "PUBLISHED",
            corpus_version_number: 2,
            previous_corpus_version_number: 1,
            actor_user_id: "22000000-0000-4000-8000-000000000001",
            evidence: { suppressed_chunk_count: 1 },
            occurred_at: "2026-08-05T10:00:00Z",
          },
          {
            id: "c3000000-0000-4000-8000-000000000001",
            action: "PUBLISHED",
            corpus_version_number: 1,
            previous_corpus_version_number: null,
            actor_user_id: "22000000-0000-4000-8000-000000000001",
            evidence: { suppressed_chunk_count: 0 },
            occurred_at: "2026-08-04T10:00:00Z",
          },
        ],
      },
    });
  });
  await page.getByRole("tab", { name: "Publication" }).click();
  await expect(
    page.getByRole("heading", { name: "Corpus publication", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Ready to publish")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-knowledge-publication.png",
    screenshotOptions,
  );
  await page.unroute(corpusPublicationActiveRoute);
  await page.unroute(corpusPublicationHistoryRoute);

  const retrievalAnalyticsSummaryRoute =
    "**/api/v1/admin/knowledge/retrieval-analytics/summary*";
  const retrievalAnalyticsZeroRoute =
    "**/api/v1/admin/knowledge/retrieval-analytics/zero-result-queries*";
  const retrievalAnalyticsLowRoute =
    "**/api/v1/admin/knowledge/retrieval-analytics/low-confidence-queries*";
  const retrievalAnalyticsGroup = {
    event_count: 3,
    surfaces: ["EMPLOYEE_AGENT", "EVIDENCE_SEARCH"],
    first_seen_at: "2026-08-10T09:00:00Z",
    last_seen_at: "2026-08-16T10:00:00Z",
    last_corpus_version_id: null,
  };
  await page.route(retrievalAnalyticsSummaryRoute, async (route) => {
    await route.fulfill({
      json: {
        window_days: 30,
        low_confidence_threshold: 0.01,
        event_count: 40,
        zero_result_count: 4,
        zero_result_rate: 0.1,
        low_confidence_count: 2,
        low_confidence_rate: 0.05,
        query_group_count: 18,
      },
    });
  });
  await page.route(retrievalAnalyticsZeroRoute, async (route) => {
    await route.fulfill({
      json: {
        window_days: 30,
        low_confidence_threshold: 0.01,
        items: [
          {
            ...retrievalAnalyticsGroup,
            kind: "ZERO_RESULT",
            normalized_query: "printer offline error",
            matching_count: 3,
            best_top_score: null,
            disposition: {
              disposition_status: "SOURCE_CANDIDATE",
              disposition_note: "Propose printer troubleshooting source",
              decided_at: "2026-08-16T12:00:00Z",
              row_version: 1,
              replayed: false,
            },
          },
          {
            ...retrievalAnalyticsGroup,
            kind: "ZERO_RESULT",
            normalized_query: "vpn setup guide",
            matching_count: 1,
            best_top_score: null,
            disposition: null,
          },
        ],
        has_more: false,
      },
    });
  });
  await page.route(retrievalAnalyticsLowRoute, async (route) => {
    await route.fulfill({
      json: {
        window_days: 30,
        low_confidence_threshold: 0.01,
        items: [
          {
            ...retrievalAnalyticsGroup,
            kind: "LOW_CONFIDENCE",
            normalized_query: "expense report rejection",
            matching_count: 2,
            best_top_score: 0.008,
            disposition: {
              disposition_status: "ACKNOWLEDGED",
              disposition_note: "Expense guidance exists",
              decided_at: "2026-08-16T11:00:00Z",
              row_version: 1,
              replayed: false,
            },
          },
        ],
        has_more: false,
      },
    });
  });
  await page.getByRole("tab", { name: "Analytics" }).click();
  await expect(
    page.getByRole("heading", { name: "Search analytics", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("40 retrieval queries")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-knowledge-analytics.png",
    screenshotOptions,
  );
  await page.unroute(retrievalAnalyticsSummaryRoute);
  await page.unroute(retrievalAnalyticsZeroRoute);
  await page.unroute(retrievalAnalyticsLowRoute);

  const retrievalSynonymsRoute =
    "**/api/v1/admin/knowledge/retrieval-synonyms*";
  await page.route(retrievalSynonymsRoute, async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            synonym_id: "31000000-0000-0000-0000-000000000001",
            term: "sso",
            expansion: "single sign on",
            synonym_status: "DRAFT",
            synonym_note: null,
            decided_at: "2026-08-17T09:00:00Z",
            row_version: 1,
            replayed: false,
          },
          {
            synonym_id: "31000000-0000-0000-0000-000000000002",
            term: "vpn",
            expansion: "virtual private network",
            synonym_status: "APPROVED",
            synonym_note: "From zero-result analytics",
            decided_at: "2026-08-16T10:00:00Z",
            row_version: 2,
            replayed: false,
          },
          {
            synonym_id: "31000000-0000-0000-0000-000000000003",
            term: "vpn",
            expansion: "remote access tunnel",
            synonym_status: "RETIRED",
            synonym_note: "Superseded wording",
            decided_at: "2026-08-15T10:00:00Z",
            row_version: 3,
            replayed: false,
          },
        ],
        has_more: false,
      },
    });
  });
  await page.getByRole("tab", { name: "Synonyms" }).click();
  await expect(
    page.getByRole("heading", { name: "Synonyms", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "virtual private network" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-knowledge-synonyms.png",
    screenshotOptions,
  );
  await page.unroute(retrievalSynonymsRoute);

  await page.getByRole("tab", { name: "Documents" }).click();
  await expect(
    page.getByRole("heading", { name: "Knowledge", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Invoice validation runbook" }).click();
  await expect(
    page.getByRole("heading", { name: "Invoice validation runbook" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(
    page.getByText(/Check the invoice validation service queue depth/),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  const fixedChrome = page.locator(".app-topbar, .skip-link");
  await fixedChrome.evaluateAll((elements) => {
    for (const element of elements) {
      if (element instanceof HTMLElement) element.style.visibility = "hidden";
    }
  });
  try {
    await expect(page.locator("#main-content")).toHaveScreenshot(
      "admin-knowledge-detail.png",
      contentScreenshotOptions,
    );
  } finally {
    await fixedChrome.evaluateAll((elements) => {
      for (const element of elements) {
        if (element instanceof HTMLElement) element.style.visibility = "";
      }
    });
  }

  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "System status" })
    .evaluate((element) => {
      if (element instanceof HTMLElement) element.click();
    });
  await expect(
    page.getByRole("heading", { name: "System status" }),
  ).toBeVisible();
  await expect(page.getByText("Migration head")).toBeVisible();
  await expect(page.getByText("Developer identity")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-system.png", screenshotOptions);

  // Identity and access: users carry live timestamps in their detail pages,
  // so user screens are asserted functionally; roles, queues, and ticket
  // views render only deterministic seeded values and are captured visually.
  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Users", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Users", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Development Platform Administrator" }),
  ).toBeVisible();
  await page.getByLabel("Search users").fill("Agent");
  await expect(
    page.getByRole("link", { name: "Development Agent", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Development Customer" }),
  ).toHaveCount(0);
  await page.getByLabel("Search users").fill("");
  const userStatusFilter = page.locator(".table-toolbar").getByRole("combobox");
  await userStatusFilter.selectOption("inactive");
  await expect(
    page.getByRole("link", { name: "Development Inactive User" }),
  ).toBeVisible();
  await userStatusFilter.selectOption("");
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await page
    .getByRole("link", { name: "Development Platform Administrator" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Development Platform Administrator" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Effective permissions" }),
  ).toBeVisible();
  await expect(page.getByText("Provisioning")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Sign-in identities", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent security events" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Roles" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Roles", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Platform Administrator" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-roles.png", screenshotOptions);

  await page.getByRole("link", { name: "Platform Administrator" }).click();
  await expect(
    page.getByRole("heading", { name: "Platform Administrator", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Permissions", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Admin identity read")).toBeVisible();
  await expect(
    page
      .locator(".data-table")
      .getByRole("link", { name: "Development Platform Administrator" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Queues", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Queues", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Development Service Desk" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-queues.png", screenshotOptions);

  await page.getByRole("link", { name: "Development Service Desk" }).click();
  await expect(
    page.getByRole("heading", { name: "Development Service Desk" }),
  ).toBeVisible();
  await expect(page.getByText("Round robin")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Members", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".data-table")
      .getByRole("link", { name: "Development Agent", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("No ticket views are owned by this queue."),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Queues", exact: true })
    .click();
  await page.getByRole("link", { name: "All ticket views" }).click();
  await expect(
    page.getByRole("heading", { name: "Ticket views" }),
  ).toBeVisible();
  await expect(page.getByText("Fusion AP group")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-ticket-views.png",
    screenshotOptions,
  );

  // Configuration administration: workflows, SLA policies, and the
  // catalogue render only deterministic seeded values in their list views.
  // Calendar and detail screens are asserted functionally in
  // admin-config.spec.ts because they mix in the mutation controls.
  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Workflows", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workflows", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Catalogue fixture workflow" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-workflows.png", screenshotOptions);

  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "SLA policies", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "SLA policies", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Time to first response" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "admin-sla-policies.png",
    screenshotOptions,
  );

  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Catalogue", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Service catalogue" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Report an Oracle Fusion error" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("admin-catalogue.png", screenshotOptions);

  // Audit rows carry live server timestamps, so this screen is asserted
  // functionally instead of visually.
  await openNavigation();
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Audit logs" })
    .click();
  await expect(page.getByRole("heading", { name: "Audit logs" })).toBeVisible();
  await expect(page.locator(".audit-row").first()).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await page.getByRole("tab", { name: "Security" }).click();
  await expect(
    page.getByText(/Privileged endpoint accessed/i).first(),
  ).toBeVisible();
  await expectAccessible(page);
});
