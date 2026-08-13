import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("analyst creates, applies, updates, reorders, and deletes personal filters", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();

  await page.getByRole("button", { name: /Unassigned.*ERP/ }).click();
  await page.getByLabel("Assignee").selectOption("unassigned");
  await page.getByLabel("Search ticket key or summary").fill("invoice");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page).toHaveURL(/assignee=unassigned/);
  await expect(page).toHaveURL(/q=invoice/);

  await page.getByLabel("Saved filter name").fill("My invoice queue");
  await page.getByRole("button", { name: "Save current filter" }).click();
  await expect(page.getByLabel("Apply a saved filter")).toHaveValue(/.+/);
  await expect(page).toHaveURL(/savedFilter=/);
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();

  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page).toHaveURL(/editFilter=/);
  await page.getByLabel("Rename saved filter").fill("My renamed invoice queue");
  await page.getByRole("button", { name: "Update saved filter" }).click();
  await expect(page.getByLabel("Apply a saved filter")).toContainText(
    "My renamed invoice queue",
  );

  await page.getByLabel("Apply a saved filter").selectOption("");
  await page.getByLabel("Saved filter name").fill("Second personal filter");
  await page.getByRole("button", { name: "Save current filter" }).click();
  await page.getByRole("button", { name: "Move up" }).click();
  await expect(
    page.getByLabel("Apply a saved filter").locator("option").nth(1),
  ).toHaveText("Second personal filter");

  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete saved filter" }).click();
  await expect(page.getByLabel("Apply a saved filter")).not.toContainText(
    "Second personal filter",
  );
  await page
    .getByLabel("Apply a saved filter")
    .selectOption({ label: "My renamed invoice queue" });
  await expect(page.getByLabel("Apply a saved filter")).toHaveValue(/.+/);

  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Delete My renamed invoice queue?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete saved filter" }).click();
  await expect(page.getByLabel("Apply a saved filter")).not.toContainText(
    "My renamed invoice queue",
  );

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations,
    accessibility.violations
      .map((violation) => `${violation.id}: ${violation.help}`)
      .join("\n"),
  ).toEqual([]);
});
