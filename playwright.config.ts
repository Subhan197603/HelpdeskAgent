import { defineConfig, devices } from "@playwright/test";

const databaseUrl =
  "postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:55449/helpdesk";

export default defineConfig({
  testDir: "./tests/end_to_end",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  globalSetup: "./tests/end_to_end/global-setup.ts",
  globalTeardown: "./tests/end_to_end/global-teardown.ts",
  use: {
    baseURL: "http://127.0.0.1:53000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "uv run python -m apps.api.app.server",
      url: "http://127.0.0.1:58010/health/live",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        APP_ENV: "development",
        API_HOST: "127.0.0.1",
        API_PORT: "58010",
        APP_BASE_URL: "http://127.0.0.1:53000",
        API_BASE_URL: "http://127.0.0.1:58010",
        CORS_ALLOWED_ORIGINS: '["http://127.0.0.1:53000"]',
        DATABASE_URL: databaseUrl,
        DEVELOPER_IDENTITY_ENABLED: "true",
        OBJECT_STORAGE_ENABLED: "false",
        OIDC_ENABLED: "false",
        TRUSTED_HOSTS: '["127.0.0.1","localhost"]',
      },
    },
    {
      command: "pnpm --filter @fusion-helpdesk/web dev --port 53000",
      url: "http://127.0.0.1:53000",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_URL: "http://127.0.0.1:58010" },
    },
  ],
});
