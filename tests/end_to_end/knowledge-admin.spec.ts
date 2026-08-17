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
});
