import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("analyst manages personal responses and inserts editable draft text only", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await page.getByRole("link", { name: "My queues", exact: true }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  let ticketLink = page.getByRole("link", { name: /ERP-\d+/ }).first();
  if ((await ticketLink.count()) === 0) {
    await page.getByRole("button", { name: "Sign out" }).click();
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
      .fill("Invoice validation fails while processing the request.");
    await page.getByLabel("Affected environment").selectOption("PROD");
    await page.getByRole("button", { name: "Review request" }).click();
    await page.getByRole("button", { name: "Confirm and submit" }).click();
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("button", { name: "Continue as analyst" }).click();
    await page.getByRole("link", { name: "My queues", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "My queues" }),
    ).toBeVisible();
    ticketLink = page.getByRole("link", { name: /ERP-\d+/ }).first();
  }
  await ticketLink.click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Activity" }).click();

  const visibility = page.getByLabel("Comment visibility");
  await visibility.selectOption("INTERNAL");
  const timelineItems = page.locator(".activity > ol > li");
  const initialCount = await timelineItems.count();

  await page.getByLabel("Response name").fill("Ask for invoice");
  await page
    .getByLabel("Response text")
    .fill("Please provide the affected invoice number.");
  await page.getByRole("button", { name: "Create response" }).click();
  await expect(page.getByLabel("Choose a canned response")).toHaveValue(/.+/);

  await page.getByRole("button", { name: "Insert response" }).click();
  const draft = page.getByLabel("Add an update");
  await expect(draft).toHaveValue(
    "Please provide the affected invoice number.",
  );
  await expect(visibility).toHaveValue("INTERNAL");
  await draft.fill("Please provide invoice ERP-99.");
  await expect(timelineItems).toHaveCount(initialCount);

  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Response name").fill("Ask for reference");
  await page.getByRole("button", { name: "Update response" }).click();
  await expect(page.getByLabel("Choose a canned response")).toContainText(
    "Ask for reference",
  );

  await page.getByLabel("Response name").fill("Closing response");
  await page.getByLabel("Response text").fill("Your request is now resolved.");
  await page.getByRole("button", { name: "Create response" }).click();
  await expect(page.getByLabel("Choose a canned response")).toContainText(
    "Closing response",
  );
  await page
    .getByLabel("Choose a canned response")
    .selectOption({ label: "Closing response" });
  await page.getByRole("button", { name: "Move up" }).click();
  await expect(
    page.getByLabel("Choose a canned response").locator("option").nth(1),
  ).toHaveText("Closing response");
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByLabel("Choose a canned response")).not.toContainText(
    "Closing response",
  );

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations,
    accessibility.violations
      .map((violation) => `${violation.id}: ${violation.help}`)
      .join("\n"),
  ).toEqual([]);
});
