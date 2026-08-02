import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const screenshotOptions = {
  animations: "disabled" as const,
  fullPage: true,
  maxDiffPixelRatio: 0.015,
};

async function expectAccessible(page: Page) {
  const result = await new AxeBuilder({ page })
    .exclude("[data-visual-only]")
    .analyze();
  expect(
    result.violations,
    result.violations.map((item) => `${item.id}: ${item.help}`).join("\n"),
  ).toEqual([]);
}

async function expectNoHorizontalScroll(page: Page) {
  const sizes = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(sizes.scroll).toBeLessThanOrEqual(sizes.client);
}

test("approved employee and analyst screens remain visually stable", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-08-02T10:30:00Z") });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();

  await expect(
    page.getByRole("heading", { name: "How can we help you?" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("employee-portal.png", screenshotOptions);

  await page
    .locator(".portal-hero")
    .getByRole("link", { name: "Browse services" })
    .click();
  await page
    .getByRole("tab", { name: /ERP.*Oracle Fusion ERP Support/ })
    .click();
  await page
    .getByRole("link", { name: /Report an Oracle Fusion error/ })
    .click();
  await expect(page.getByLabel("Brief summary")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "dynamic-request-form.png",
    screenshotOptions,
  );

  await page.getByLabel("Brief summary").fill("Oracle Fusion invoice error");
  await page
    .getByLabel("Detailed description")
    .fill("Invoice validation fails with an unexpected application error.");
  await page.getByLabel("Affected environment").selectOption("PROD");
  await page.getByRole("button", { name: "Review request" }).click();
  await expect(
    page.getByRole("heading", { name: "Review your request" }),
  ).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "submission-review.png",
    screenshotOptions,
  );

  await page.getByRole("button", { name: "Confirm and submit" }).click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Attachments" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "customer-ticket-detail.png",
    screenshotOptions,
  );

  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("analyst-queue.png", screenshotOptions);

  await page
    .getByRole("link", { name: /Oracle Fusion invoice error/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await expect(page.getByLabel("Comment visibility")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-ticket-detail.png",
    screenshotOptions,
  );
});
