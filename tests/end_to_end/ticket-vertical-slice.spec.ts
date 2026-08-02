import { expect, test } from "@playwright/test";

test("employee submits an Oracle Fusion issue and exchanges a public comment", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();
  await page.getByRole("link", { name: "Browse services" }).first().click();

  await page
    .getByRole("tab", { name: /ERP.*Oracle Fusion ERP Support/ })
    .click();
  await page
    .getByRole("link", { name: /Report an Oracle Fusion error/ })
    .click();
  await page.getByLabel("Brief summary").fill("Oracle Fusion invoice error");
  await page
    .getByLabel("Detailed description")
    .fill("Invoice validation fails with an unexpected application error.");
  await page.getByLabel("Affected environment").selectOption("PROD");
  await page.getByRole("button", { name: "Review request" }).click();

  await expect(
    page.getByRole("heading", { name: "Review your request" }),
  ).toBeVisible();
  await expect(page.getByText("Oracle Fusion invoice error")).toBeVisible();
  await page.getByRole("button", { name: "Confirm and submit" }).click();

  await expect(page.getByText("ERP-1", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await expect(page.getByLabel("Comment visibility")).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Unassigned.*ERP/ }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /ERP-1/ })).toBeVisible();
  await page.getByRole("link", { name: /ERP-1/ }).click();
  await expect(page.getByLabel("Comment visibility")).toBeVisible();
  await page
    .getByLabel("Add an update")
    .fill("We are investigating the invoice validation service.");
  await page.getByRole("button", { name: "Post public comment" }).click();
  await expect(
    page.getByText("We are investigating the invoice validation service."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: "Continue as employee" }).click();
  await page
    .getByRole("link", { name: "My tickets", exact: true })
    .first()
    .click();
  await page.getByRole("link", { name: /ERP-1/ }).click();
  await expect(
    page.getByText("We are investigating the invoice validation service."),
  ).toBeVisible();
});
