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

test("caller without knowledge administration permission is denied", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();
  await page.goto("/admin/knowledge");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();
});
