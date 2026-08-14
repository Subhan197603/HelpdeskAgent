import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("analyst watches, follows, and unwatches a personal ticket", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();
  await page.getByRole("link", { name: "Browse services" }).first().click();
  await page
    .getByRole("tab", { name: /ERP.*Oracle Fusion ERP Support/ })
    .click();
  await page
    .getByRole("link", { name: /Report an Oracle Fusion error/ })
    .click();
  await page.getByLabel("Brief summary").fill("Watchlist validation ticket");
  await page
    .getByLabel("Detailed description")
    .fill("Validate personal ticket watchlist behavior without side effects.");
  await page.getByLabel("Affected environment").selectOption("TEST");
  await page.getByRole("button", { name: "Review request" }).click();
  await page.getByRole("button", { name: "Confirm and submit" }).click();
  const submittedKey = page.getByText(/^ERP-\d+$/, { exact: true });
  await expect(submittedKey).toBeVisible();
  const ticketKey = (await submittedKey.textContent())?.match(/ERP-\d+/)?.[0];
  expect(ticketKey).toBeTruthy();
  if (!ticketKey) throw new Error("Expected the submitted ERP ticket key.");

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();

  const ticketLink = page
    .getByRole("link", { name: new RegExp(ticketKey) })
    .first();
  await expect(ticketLink).toBeVisible();
  await ticketLink.click();

  await page.getByRole("tab", { name: "Activity" }).click();
  const timelineItems = page.locator(".activity > ol > li");
  const initialTimelineCount = await timelineItems.count();
  await page.getByRole("button", { name: "Watch", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Unwatch", exact: true }),
  ).toBeVisible();
  await expect(timelineItems).toHaveCount(initialTimelineCount);

  await page.getByRole("link", { name: "Tickets", exact: true }).click();
  await page.getByRole("button", { name: "Watched tickets" }).click();
  await expect(
    page.getByRole("heading", { name: "Watched tickets" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: new RegExp(ticketKey) }),
  ).toBeVisible();
  await expect(page).toHaveURL(/view=watched/);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations,
    accessibility.violations
      .map((violation) => `${violation.id}: ${violation.help}`)
      .join("\n"),
  ).toEqual([]);
  const widths = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client);

  await page.getByRole("link", { name: new RegExp(ticketKey) }).click();
  await expect(
    page.getByRole("button", { name: "Unwatch", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Unwatch", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Watch", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Tickets", exact: true }).click();
  await page.getByRole("button", { name: "Watched tickets" }).click();
  await expect(page.getByText("No watched tickets yet.")).toBeVisible();
});
