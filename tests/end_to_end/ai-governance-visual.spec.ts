import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("AI governance remains readable at the approved viewport", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.goto("/admin/ai");
  await expect(
    page.getByRole("heading", { name: "AI governance", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Platform disabled").first()).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  const horizontal = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(horizontal.scroll).toBeLessThanOrEqual(horizontal.client);
  await expect(page).toHaveScreenshot("admin-ai-governance.png", {
    animations: "disabled",
    fullPage: true,
    maxDiffPixelRatio: 0.015,
  });
});
