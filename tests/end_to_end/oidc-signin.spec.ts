import { expect, test } from "@playwright/test";

// Runs against the OIDC-only stack (web :53001, api :58011, stub IdP :59180)
// with DEVELOPER_IDENTITY_ENABLED=false — the production authentication
// posture that DEF-RC1-001 requires the browser to support.

test("signs in through the identity provider with PKCE and loads the workspace", async ({
  page,
}) => {
  const developerHeaderRequests: string[] = [];
  page.on("request", (request) => {
    if (request.headers()["x-developer-user"])
      developerHeaderRequests.push(request.url());
  });

  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /continue as employee/i }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /continue as analyst/i }),
  ).toHaveCount(0);
  await expect(page.getByText(/development identity mode/i)).toHaveCount(0);

  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Development Agent").first()).toBeVisible();
  await expect(page.getByLabel("Application navigation")).toBeVisible();

  const storedTokens = await page.evaluate(() => {
    const values = [
      ...Object.values({ ...localStorage }),
      ...Object.values({ ...sessionStorage }),
    ].join(" ");
    return /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\./.test(values);
  });
  expect(storedTokens).toBe(false);
  expect(developerHeaderRequests).toEqual([]);
});

test("rejects a forged callback state", async ({ page }) => {
  await page.goto("/auth/callback?code=forged-code&state=forged-state");
  await expect(page.getByText(/sign-in could not complete/i)).toBeVisible();
  await expect(
    page.getByRole("link", { name: /return to sign in/i }),
  ).toBeVisible();
});

test("signing out returns to the single sign-on entry point", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Development Agent").first()).toBeVisible();

  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  const hasSessionResidue = await page.evaluate(
    () => localStorage.getItem("fusion-helpdesk-session") !== null,
  );
  expect(hasSessionResidue).toBe(false);
});
