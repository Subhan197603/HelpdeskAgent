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
  const openNavigation = async () => {
    const menu = page.getByRole("button", { name: "Open navigation" });
    if (await menu.isVisible()) await menu.click();
  };
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

  // Knowledge base: landing, search, and article detail against seeded corpus.
  await openNavigation();
  await page.getByRole("link", { name: "Knowledge base" }).click();
  await expect(
    page.getByRole("heading", { name: "Knowledge Base" }),
  ).toBeVisible();
  await expect(page.getByText("Browse by type")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Oracle Fusion login issues" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Invoice validation runbook" }),
  ).toHaveCount(0);
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "knowledge-landing.png",
    screenshotOptions,
  );

  await page.getByLabel("Search knowledge articles").fill("password");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText(/Results for/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Oracle Fusion login issues" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Password reset guide" }),
  ).toBeVisible();
  await expect(page.locator("mark").first()).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "knowledge-search.png",
    screenshotOptions,
  );

  await page.getByRole("link", { name: "Oracle Fusion login issues" }).click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion login issues", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Article information" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "View original source" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "knowledge-article.png",
    screenshotOptions,
  );

  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.getByRole("button", { name: "Continue as analyst" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot("analyst-queue.png", screenshotOptions);

  await openNavigation();
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Open Tickets", { exact: true })).toBeVisible();
  await expect(page.getByText("SLA Compliance (This Week)")).toBeVisible();
  await expect(page.getByText("Recent Activity")).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Open tickets by status/ }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-dashboard.png",
    screenshotOptions,
  );

  // Analyst knowledge: the confidential runbook is visible only here.
  await openNavigation();
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Knowledge Base" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Invoice validation runbook" }),
  ).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);

  await openNavigation();
  await page.getByRole("link", { name: "My queues" }).click();
  await expect(page.getByRole("heading", { name: "My queues" })).toBeVisible();

  await page
    .getByRole("link", { name: /Oracle Fusion invoice error/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Oracle Fusion invoice error" }),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("Assignment group")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-ticket-detail.png",
    screenshotOptions,
  );

  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(page.getByLabel("Comment visibility")).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveScreenshot(
    "analyst-ticket-activity.png",
    screenshotOptions,
  );

  await page.getByRole("tab", { name: "Attachments" }).click();
  await expect(page.getByText("No attachments yet.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Attachments", exact: true }),
  ).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.getByRole("tab", { name: "Participants" }).click();
  await expect(
    page.getByText("Participant management is not yet available"),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Work Log" }).click();
  await expect(
    page.getByText("Work log tracking arrives with a future milestone."),
  ).toBeVisible();
  await expectAccessible(page);

  // Server-truth actions: execute a real status transition last so earlier
  // screenshots stay deterministic.
  await page.getByRole("tab", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Change status" }).click();
  await page.getByRole("menuitem", { name: /In Progress|Start/ }).click();
  await expect(
    page.locator(".detail-header__badges").getByText(/in progress/i),
  ).toBeVisible();
});
