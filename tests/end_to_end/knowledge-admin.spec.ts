import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("administrator reviews governed knowledge without authoring controls", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/knowledge"]').click();

  await expect(page.getByRole("heading", { name: "Knowledge" })).toBeVisible();
  await expect(page.getByText("4 tenant articles")).toBeVisible();
  await page.getByLabel("Search article titles").fill("Invoice");
  await expect(
    page.getByRole("link", { name: "Invoice validation runbook" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Password reset guide" }),
  ).toBeHidden();

  await page.getByRole("link", { name: "Invoice validation runbook" }).click();
  await expect(
    page.getByRole("heading", { name: "Invoice validation runbook" }),
  ).toBeVisible();
  await expect(page.getByText("Analyst", { exact: true })).toBeVisible();
  await expect(page.getByText("Confidential", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Restore" })).toHaveCount(0);
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(
    page.getByText(/Check the invoice validation service queue depth/),
  ).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("administrator manages the approved-source refresh lifecycle", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/knowledge"]').click();
  await page.getByRole("tab", { name: "Sources" }).click();

  await expect(
    page.getByRole("heading", { name: "Knowledge sources" }),
  ).toBeVisible();
  await expect(page.getByText("3 governed sources")).toBeVisible();
  const handbook = page.getByRole("row", { name: /DEV_HANDBOOK/ });
  await expect(handbook.getByText("Current")).toBeVisible();

  await handbook.getByRole("button", { name: "Mark for refresh" }).click();
  await expect(
    page.getByRole("heading", { name: "Change refresh lifecycle" }),
  ).toBeVisible();
  await expect(page.getByText(/never starts an acquisition run/)).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Mark for refresh" })
    .click();
  await expect(handbook.getByText("Refresh due")).toBeVisible();

  await page.getByLabel("Refresh state").selectOption("REFRESH_DUE");
  await expect(page.getByText("1 governed sources")).toBeVisible();
  await expect(handbook).toBeVisible();
  await page.getByLabel("Refresh state").selectOption("");

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await handbook.getByRole("button", { name: "Mark current" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Mark current" })
    .click();
  await expect(handbook.getByText("Refresh due")).toBeHidden();
  await expect(handbook.getByText("Current")).toBeVisible();

  await expect(
    handbook.getByRole("button", { name: "Run refresh" }),
  ).toBeVisible();
  await handbook.getByRole("button", { name: "View changes" }).click();
  await expect(
    page.getByRole("heading", { name: /Change report — DEV_HANDBOOK/ }),
  ).toBeVisible();
  await expect(page.getByText("No change report")).toBeVisible();
  await expect(
    page.getByText("No refresh run has been recorded for this source yet."),
  ).toBeVisible();
  const reportAccessibility = await new AxeBuilder({ page }).analyze();
  expect(reportAccessibility.violations).toEqual([]);
  await page.getByRole("button", { name: "Close report" }).click();
  await expect(
    page.getByRole("heading", { name: /Change report — DEV_HANDBOOK/ }),
  ).toBeHidden();
});

test("administrator reviews the corpus validation report", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/knowledge"]').click();

  const latestRoute = "**/api/v1/admin/knowledge/corpus-validations/latest";
  await page.route(latestRoute, async (route) => {
    await route.fulfill({
      json: {
        run_id: null,
        status: null,
        requested_by: null,
        similarity_threshold: null,
        document_count: 0,
        chunk_count: 0,
        truncated: false,
        started_at: null,
        completed_at: null,
        summary: {
          structural_defects: 0,
          empty_chunks: 0,
          duplicate_documents: 0,
          near_duplicate_chunks: 0,
        },
        findings: [],
        replayed: false,
      },
    });
  });
  await page.getByRole("tab", { name: "Validation" }).click();
  await expect(
    page.getByRole("heading", { name: "Corpus validation" }),
  ).toBeVisible();
  await expect(page.getByText("No validation run yet")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run validation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run validation" }).click();
  await expect(
    page.getByRole("heading", { name: "Run corpus validation" }),
  ).toBeVisible();
  await expect(
    page.getByText(/nothing is published, removed, or hidden/),
  ).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel" })
    .click();
  await page.unroute(latestRoute);
});

test("administrator publishes the corpus and reviews version history", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/knowledge"]').click();

  const activeRoute = "**/api/v1/admin/knowledge/corpus-publications/active";
  const historyRoute = "**/api/v1/admin/knowledge/corpus-publications";
  const version = {
    id: "c2000000-0000-4000-8000-000000000001",
    version_number: 1,
    validation_run_id: "c1000000-0000-4000-8000-000000000001",
    published_by: "22000000-0000-4000-8000-000000000001",
    published_at: "2026-08-05T10:00:00Z",
    document_count: 12,
    chunk_count: 42,
    suppressed_chunk_count: 2,
    active: true,
    replayed: false,
  };
  await page.route(activeRoute, async (route) => {
    await route.fulfill({
      json: {
        active_version: version,
        readiness: {
          publishable: true,
          blockers: [],
          validation_run_id: "c1000000-0000-4000-8000-000000000001",
          suppression_flagged_chunks: 2,
        },
      },
    });
  });
  await page.route(historyRoute, async (route) => {
    await route.fulfill({
      json: {
        versions: [version],
        events: [
          {
            id: "c3000000-0000-4000-8000-000000000001",
            action: "PUBLISHED",
            corpus_version_number: 1,
            previous_corpus_version_number: null,
            actor_user_id: "22000000-0000-4000-8000-000000000001",
            evidence: { suppressed_chunk_count: 2 },
            occurred_at: "2026-08-05T10:00:00Z",
          },
        ],
      },
    });
  });
  await page.getByRole("tab", { name: "Publication" }).click();
  await expect(
    page.getByRole("heading", { name: "Corpus publication" }),
  ).toBeVisible();
  await expect(page.getByText("Ready to publish")).toBeVisible();
  await expect(
    page.getByText("2 chunks flagged for suppression"),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Corpus version history" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Corpus publication events" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Publish corpus" }).click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Publish corpus" }),
  ).toBeVisible();
  await expect(
    page.getByText(/canonical copy of duplicated content is never suppressed/),
  ).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel" })
    .click();
  await page.unroute(activeRoute);
  await page.unroute(historyRoute);
});

test("administrator reviews retrieval search analytics", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/knowledge"]').click();

  const summaryRoute = "**/api/v1/admin/knowledge/retrieval-analytics/summary*";
  const zeroRoute =
    "**/api/v1/admin/knowledge/retrieval-analytics/zero-result-queries*";
  const lowRoute =
    "**/api/v1/admin/knowledge/retrieval-analytics/low-confidence-queries*";
  const group = {
    event_count: 3,
    surfaces: ["EMPLOYEE_AGENT", "EVIDENCE_SEARCH"],
    first_seen_at: "2026-08-10T09:00:00Z",
    last_seen_at: "2026-08-16T10:00:00Z",
    last_corpus_version_id: null,
  };
  await page.route(summaryRoute, async (route) => {
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
  await page.route(zeroRoute, async (route) => {
    await route.fulfill({
      json: {
        window_days: 30,
        low_confidence_threshold: 0.01,
        items: [
          {
            ...group,
            kind: "ZERO_RESULT",
            normalized_query: "printer offline error",
            matching_count: 3,
            best_top_score: null,
          },
        ],
        has_more: false,
      },
    });
  });
  await page.route(lowRoute, async (route) => {
    await route.fulfill({
      json: {
        window_days: 30,
        low_confidence_threshold: 0.01,
        items: [
          {
            ...group,
            kind: "LOW_CONFIDENCE",
            normalized_query: "expense report rejection",
            matching_count: 2,
            best_top_score: 0.008,
          },
        ],
        has_more: false,
      },
    });
  });
  await page.getByRole("tab", { name: "Analytics" }).click();
  await expect(
    page.getByRole("heading", { name: "Search analytics" }),
  ).toBeVisible();
  await expect(
    page.getByText("40 retrieval queries · 4 zero-result (10.0%)"),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Zero-result queries" }),
  ).toBeVisible();
  await expect(page.getByText("printer offline error")).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Low-confidence queries" }),
  ).toBeVisible();
  await expect(page.getByText("expense report rejection")).toBeVisible();
  await expect(page.getByText("Employee agent, Evidence search")).toHaveCount(
    2,
  );
  await page.getByLabel("Window").selectOption("7");
  await expect(page.getByText("40 retrieval queries")).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.unroute(summaryRoute);
  await page.unroute(zeroRoute);
  await page.unroute(lowRoute);
});

test("caller without knowledge administration permission is denied", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();
  await page.goto("/admin/knowledge");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();
  await page.goto("/admin/knowledge/sources");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();
  await page.goto("/admin/knowledge/validation");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();
  await page.goto("/admin/knowledge/analytics");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();
});
