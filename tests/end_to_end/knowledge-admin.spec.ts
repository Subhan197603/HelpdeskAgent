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
    expanded_event_count: 2,
    expanded_zero_result_count: 1,
    unexpanded_zero_result_count: 2,
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
        expansion_applied_count: 6,
        expansion_applied_rate: 0.15,
        query_group_count: 18,
      },
    });
  });
  const dispositionRoute =
    "**/api/v1/admin/knowledge/retrieval-analytics/dispositions";
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
            disposition: null,
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
  await page.route(dispositionRoute, async (route) => {
    await route.fulfill({
      status: 201,
      json: {
        disposition_status: "SOURCE_CANDIDATE",
        disposition_note: null,
        decided_at: "2026-08-16T12:00:00Z",
        row_version: 1,
        replayed: false,
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
  await expect(page.getByText("6 expanded (15.0%)")).toBeVisible();
  await expect(page.getByRole("cell", { name: "2 · 1 zero" })).toHaveCount(2);
  await expect(page.getByRole("cell", { name: "Acknowledged" })).toBeVisible();
  await page.getByLabel("Window").selectOption("7");
  await expect(page.getByText("40 retrieval queries")).toBeVisible();

  await page
    .getByRole("table", { name: "Zero-result queries" })
    .getByRole("button", { name: "Disposition" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Record gap disposition" }),
  ).toBeVisible();
  await expect(
    page.getByText(/never creates sources, starts acquisition/),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("combobox")
    .selectOption("SOURCE_CANDIDATE");
  await page
    .getByRole("dialog")
    .getByLabel("Note")
    .fill("Propose printer troubleshooting source");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Record disposition" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Record gap disposition" }),
  ).toBeHidden();
  await page.unroute(summaryRoute);
  await page.unroute(zeroRoute);
  await page.unroute(lowRoute);
  await page.unroute(dispositionRoute);
});

test("administrator manages the synonym registry", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/knowledge"]').click();

  const synonymsRoute = "**/api/v1/admin/knowledge/retrieval-synonyms*";
  await page.route(synonymsRoute, async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({
        status: 201,
        json: {
          synonym_id: "31000000-0000-0000-0000-000000000002",
          term: "vpn",
          expansion: "virtual private network",
          synonym_status: "RETIRED",
          synonym_note: "Superseded wording",
          decided_at: "2026-08-18T12:00:00Z",
          row_version: 3,
          replayed: false,
        },
      });
      return;
    }
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
        ],
        has_more: false,
      },
    });
  });
  await page.getByRole("tab", { name: "Synonyms" }).click();
  await expect(page.getByRole("heading", { name: "Synonyms" })).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Synonym registry" }),
  ).toBeVisible();
  await expect(page.getByRole("cell", { name: "sso" })).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "virtual private network" }),
  ).toBeVisible();
  await expect(page.getByRole("cell", { name: "Approved" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Draft" })).toBeVisible();

  await page
    .getByRole("row", { name: /virtual private network/ })
    .getByRole("button", { name: "Change" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Change synonym entry" }),
  ).toBeVisible();
  await expect(page.getByText(/never alter retrieval behavior/)).toBeVisible();
  await expect(page.getByRole("dialog").getByLabel("Term")).toBeDisabled();
  await page.getByRole("dialog").getByRole("combobox").selectOption("RETIRED");
  await page.getByRole("dialog").getByLabel("Note").fill("Superseded wording");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Record change" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Change synonym entry" }),
  ).toBeHidden();
  await page.unroute(synonymsRoute);
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
  await page.goto("/admin/knowledge/synonyms");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();
});
