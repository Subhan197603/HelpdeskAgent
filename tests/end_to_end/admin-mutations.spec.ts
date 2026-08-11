import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function expectAccessible(page: Page) {
  const result = await new AxeBuilder({ page })
    .exclude("[data-visual-only]")
    .analyze();
  expect(
    result.violations,
    result.violations.map((item) => `${item.id}: ${item.help}`).join("\n"),
  ).toEqual([]);
}

// Every mutation in this journey is reverted before the test ends so the shared
// database keeps its deterministic personas for the visual projects that follow.
test("administrator performs reversible access mutations end to end", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();

  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Users", exact: true })
    .click();
  await page.getByRole("link", { name: "Development Customer" }).click();
  await expect(
    page.getByRole("heading", { name: "Development Customer" }),
  ).toBeVisible();

  // Assign a role, then remove it through the named confirmation dialog.
  const roleToolbar = page.getByRole("group", { name: "Role assignment" });
  await roleToolbar
    .getByRole("combobox")
    .selectOption({ label: "Support Analyst" });
  await roleToolbar.getByRole("button", { name: "Assign role" }).click();
  await expect(
    page.locator(".data-table").getByRole("link", { name: "Support Analyst" }),
  ).toBeVisible();
  await expectAccessible(page);

  await page
    .getByRole("row", { name: /Support Analyst/ })
    .getByRole("button", { name: "Remove" })
    .click();
  const removeRoleDialog = page.getByRole("dialog", {
    name: "Remove the Support Analyst role?",
  });
  await expect(removeRoleDialog).toBeVisible();
  await expectAccessible(page);
  await removeRoleDialog.getByRole("button", { name: "Remove role" }).click();
  await expect(
    page.locator(".data-table").getByRole("link", { name: "Support Analyst" }),
  ).toHaveCount(0);

  // Deactivate, then reactivate, both behind concrete confirmations.
  await page.getByRole("button", { name: "Deactivate user" }).click();
  const deactivateDialog = page.getByRole("dialog", {
    name: "Deactivate Development Customer?",
  });
  await expect(deactivateDialog).toContainText("no longer be able to sign in");
  await deactivateDialog
    .getByRole("button", { name: "Deactivate", exact: true })
    .click();
  await expect(
    page.locator(".page-header").getByText("Inactive", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Reactivate user" }).click();
  const reactivateDialog = page.getByRole("dialog", {
    name: "Reactivate Development Customer?",
  });
  await expect(reactivateDialog).toContainText("sign in again");
  await reactivateDialog
    .getByRole("button", { name: "Reactivate", exact: true })
    .click();
  await expect(
    page.locator(".page-header").getByText("Active", { exact: true }),
  ).toBeVisible();

  // Queue membership add and remove on a real support group.
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Queues", exact: true })
    .click();
  await page
    .getByRole("link", { name: "Fusion Accounts Payable Support" })
    .click();
  const membershipToolbar = page.getByRole("group", {
    name: "Queue membership",
  });
  await membershipToolbar
    .getByRole("combobox")
    .first()
    .selectOption({ label: "Development Customer" });
  await membershipToolbar.getByRole("combobox").nth(1).selectOption("OBSERVER");
  await membershipToolbar.getByRole("button", { name: "Add to queue" }).click();
  const memberRow = page.getByRole("row", { name: /Development Customer/ });
  await expect(memberRow).toContainText("Observer");
  await expectAccessible(page);

  await memberRow.getByRole("button", { name: "Remove" }).click();
  const memberDialog = page.getByRole("dialog", {
    name: "Remove Development Customer from Fusion Accounts Payable Support?",
  });
  await expect(memberDialog).toContainText("manual reassignment");
  await memberDialog.getByRole("button", { name: "Remove member" }).click();
  // Removal is a soft deactivation: the historical membership row stays
  // visible with an Inactive badge and the active member count drops.
  await expect(
    page.getByRole("row", { name: /Development Customer/ }),
  ).toContainText("Inactive");

  // A caller without administration permissions sees no admin surface at all;
  // the server, not the frontend, is the authorization boundary.
  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  await page.goto("/admin/users");
  await expect(page.getByText("You are not authorized")).toBeVisible();
});
