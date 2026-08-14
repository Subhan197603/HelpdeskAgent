import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("analyst keyboard accelerators navigate and focus without mutation", async ({
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
  await page.getByLabel("Brief summary").fill("Keyboard validation ticket");
  await page
    .getByLabel("Detailed description")
    .fill("Validate non-destructive analyst keyboard accelerators.");
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

  const mutations: string[] = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) {
      mutations.push(`${request.method()} ${request.url()}`);
    }
  });

  await page.keyboard.press("Shift+/");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(help).not.toBeVisible();

  await page.keyboard.press("g");
  await page.keyboard.press("d");
  await expect(page).toHaveURL(/\/agent\/dashboard$/);
  await page.keyboard.press("g");
  await page.keyboard.press("q");
  await expect(page).toHaveURL(/\/agent\/tickets(?:\?|$)/);

  await page.keyboard.press("/");
  await expect(
    page.getByRole("textbox", { name: "Search ticket key or summary" }),
  ).toBeFocused();
  await page.locator("main").focus();
  await page.keyboard.press("f");
  await expect(page.getByLabel("Apply a saved filter")).toBeFocused();
  await page.locator("main").focus();
  await page.keyboard.press("j");
  await expect(
    page.getByRole("link", { name: new RegExp(ticketKey) }).first(),
  ).toBeFocused();

  await page.keyboard.press("g");
  await page.keyboard.press("k");
  await expect(page).toHaveURL(/\/agent\/knowledge$/);
  await page.keyboard.press("/");
  await expect(page.getByLabel("Search knowledge articles")).toBeFocused();

  await page.goto(`/agent/tickets/${ticketKey}`);
  await page.getByRole("tab", { name: "Activity" }).click();
  await page.locator("main").focus();
  await page.keyboard.press("f");
  await expect(page.getByLabel("Choose a canned response")).toBeFocused();
  const draft = page.getByLabel("Add an update");
  await draft.click();
  await page.keyboard.type("gq?fjk/");
  await expect(draft).toHaveValue("gq?fjk/");
  await expect(page).toHaveURL(new RegExp(`/agent/tickets/${ticketKey}`));

  await draft.evaluate((element) => {
    (element as HTMLElement).blur();
  });
  await page.keyboard.press("Shift+/");
  await expect(help).toBeVisible();
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
  expect(mutations).toEqual([]);
});
