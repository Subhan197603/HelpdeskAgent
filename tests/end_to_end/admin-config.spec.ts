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

// The visibility toggles are reverted before the test ends so the shared
// database keeps its deterministic catalogue for the visual projects.
test("administrator reviews configuration and toggles catalogue visibility", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();

  // Workflow configuration is fully readable: statuses, transitions with
  // their guards and required fields, version lifecycle, and mappings.
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Workflows", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workflows", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Catalogue fixture workflow" }).click();
  await expect(
    page.getByRole("heading", { name: "Catalogue fixture workflow" }),
  ).toBeVisible();
  const newStatusRow = page.getByRole("row", { name: /New/ }).first();
  await expect(newStatusRow).toContainText("Initial");
  await expect(page.getByRole("row", { name: /Closed/ })).toContainText(
    "Terminal",
  );
  await expectAccessible(page);

  await page.getByRole("tab", { name: "Transitions" }).click();
  const resolveRow = page.getByRole("row", { name: /Resolve/ }).first();
  await expect(resolveRow).toContainText("In progress → Resolved");
  await expect(resolveRow).toContainText("resolution_code");
  await expect(
    page.getByRole("row", { name: /Wait for customer/ }),
  ).toContainText("summary is set");
  await expectAccessible(page);

  await page.getByRole("tab", { name: "Versions" }).click();
  await expect(page.getByRole("row", { name: /v1/ })).toContainText(
    "Published",
  );

  await page.getByRole("tab", { name: "Request types" }).click();
  await expect(
    page
      .locator(".data-table")
      .getByRole("link", { name: "Report an Oracle Fusion error" }),
  ).toBeVisible();

  // SLA policies expose the values the engine actually uses: goal-version
  // targets, pause conditions, and the pinned business calendar.
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "SLA policies", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "SLA policies", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Time to resolution" }).click();
  await expect(
    page.getByRole("heading", { name: "Time to resolution" }),
  ).toBeVisible();
  await expect(page.getByText("Pauses while")).toBeVisible();
  await expect(
    page.getByText("Ticket status is WAITING_FOR_CUSTOMER"),
  ).toBeVisible();
  const p1Goal = page.getByRole("row", { name: /P1 resolution/ });
  await expect(p1Goal).toContainText("4h");
  await expect(p1Goal).toContainText("UK Business Hours");
  await expectAccessible(page);

  // Calendars show working windows, holidays, and which goals rely on them.
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Calendars", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Business calendars" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "UK Business Hours" }).click();
  await expect(
    page.getByRole("heading", { name: "UK Business Hours" }),
  ).toBeVisible();
  const mondayRow = page.getByRole("row", { name: /Monday/ });
  await expect(mondayRow).toContainText("09:00");
  await expect(mondayRow).toContainText("17:00");
  await expect(page.getByRole("row", { name: /Christmas Day/ })).toContainText(
    "Closed",
  );
  await expect(
    page.getByText("RESOLUTION: P1 resolution", { exact: true }),
  ).toBeVisible();
  await expectAccessible(page);

  // Catalogue detail: the one safe mutation — portal visibility — behind
  // named confirmation dialogs, fully reverted afterwards.
  await page
    .locator(".sidebar-nav")
    .getByRole("link", { name: "Catalogue", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Service catalogue" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Report an analytics issue" }).click();
  await expect(
    page.getByRole("heading", { name: "Report an analytics issue" }),
  ).toBeVisible();
  const summaryFieldRow = page.getByRole("row", { name: /Brief summary/ });
  await expect(summaryFieldRow).toContainText("Required");
  await expectAccessible(page);

  await page.getByRole("button", { name: "Hide from portal" }).click();
  const hideDialog = page.getByRole("dialog", {
    name: "Hide Report an analytics issue from the portal?",
  });
  await expect(hideDialog).toContainText("disappears from the employee portal");
  await expectAccessible(page);
  await hideDialog.getByRole("button", { name: "Hide", exact: true }).click();
  await expect(
    page.locator(".metadata-grid").getByText("Hidden", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Show in portal" }).click();
  const showDialog = page.getByRole("dialog", {
    name: "Show Report an analytics issue in the portal?",
  });
  await showDialog.getByRole("button", { name: "Show", exact: true }).click();
  await expect(
    page.locator(".metadata-grid").getByText("Visible", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Disable request type" }).click();
  const disableDialog = page.getByRole("dialog", {
    name: "Disable Report an analytics issue?",
  });
  await expect(disableDialog).toContainText(
    "Tickets already submitted keep their form and workflow.",
  );
  await disableDialog
    .getByRole("button", { name: "Disable", exact: true })
    .click();
  await expect(
    page.locator(".metadata-grid").getByText("Inactive", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Enable request type" }).click();
  const enableDialog = page.getByRole("dialog", {
    name: "Enable Report an analytics issue?",
  });
  await enableDialog
    .getByRole("button", { name: "Enable", exact: true })
    .click();
  await expect(
    page.locator(".metadata-grid").getByText("Active", { exact: true }),
  ).toBeVisible();

  // The server, not the sidebar, is the authorization boundary.
  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  await page.goto("/admin/workflows");
  await expect(page.getByText("You are not authorized")).toBeVisible();
  await page.goto("/admin/catalogue");
  await expect(page.getByText("You are not authorized")).toBeVisible();
});
