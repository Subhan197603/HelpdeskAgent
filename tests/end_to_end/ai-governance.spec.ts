import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("AI administrator reviews safety state without mutation controls", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as administrator" }).click();
  await page.locator('a[href="/admin/ai"]').click();

  await expect(
    page.getByRole("heading", { name: "AI governance", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Platform disabled").first()).toBeVisible();
  await expect(page.getByText("Service restart")).toBeVisible();
  await expect(page.getByText("Availability not probed").first()).toBeVisible();
  await expect(
    page.getByRole("button", { name: /enable|disable|reset/i }),
  ).toHaveCount(0);
  await expect(page.getByText(/No completed AI provider calls/)).toBeVisible();
  const horizontal = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(horizontal.scroll).toBeLessThanOrEqual(horizontal.client);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("caller without AI oversight is denied in the route and API", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as employee" }).click();
  await page.goto("/admin/ai");
  await expect(
    page.getByRole("heading", { name: "You are not authorized" }),
  ).toBeVisible();

  const response = await page.request.get(
    "http://127.0.0.1:58110/api/v1/admin/ai",
    {
      headers: { "X-Developer-User": "DEV/customer" },
    },
  );
  expect(response.status()).toBe(403);
});
