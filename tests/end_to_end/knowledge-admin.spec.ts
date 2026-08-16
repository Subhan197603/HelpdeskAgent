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
});
