import { defineConfig, devices } from "@playwright/test";

const databaseUrl =
  "postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:55549/helpdesk";

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
      name: "functional-chromium",
      testMatch: /ticket-vertical-slice\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { height: 800, width: 1280 },
      },
    },
    {
      name: "oidc-chromium",
      testMatch: /oidc-signin\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: "http://127.0.0.1:53001",
        viewport: { height: 800, width: 1280 },
      },
    },
    ...[
      { height: 1024, name: "visual-1440", width: 1440 },
      { height: 800, name: "visual-1280", width: 1280 },
      { height: 1024, name: "visual-768", width: 768 },
      { height: 844, name: "visual-390", width: 390 },
    ].map(({ height, name, width }) => ({
      name,
      testMatch: /visual-foundation\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { height, width } },
    })),
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
        CLAMAV_HOST: "127.0.0.1",
        CORS_ALLOWED_ORIGINS: '["http://127.0.0.1:53000"]',
        DATABASE_URL: databaseUrl,
        DEVELOPER_IDENTITY_ENABLED: "true",
        REDIS_URL: "redis://127.0.0.1:6379/0",
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
    {
      command: "node tests/end_to_end/oidc-stub-idp.mjs",
      url: "http://127.0.0.1:59180/.well-known/openid-configuration",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "uv run python -m apps.api.app.server",
      url: "http://127.0.0.1:58011/health/live",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        APP_ENV: "development",
        API_HOST: "127.0.0.1",
        API_PORT: "58011",
        APP_BASE_URL: "http://127.0.0.1:53001",
        API_BASE_URL: "http://127.0.0.1:58011",
        CLAMAV_HOST: "127.0.0.1",
        CORS_ALLOWED_ORIGINS: '["http://127.0.0.1:53001"]',
        DATABASE_URL: databaseUrl,
        DEVELOPER_IDENTITY_ENABLED: "false",
        REDIS_URL: "redis://127.0.0.1:6379/0",
        OBJECT_STORAGE_ENABLED: "false",
        OIDC_ENABLED: "true",
        OIDC_PROVIDER_CODE: "TEST_OIDC",
        OIDC_ISSUER_URL: "http://127.0.0.1:59180",
        OIDC_AUDIENCE: "helpdesk-e2e-api",
        OIDC_CLIENT_ID: "helpdesk-e2e-spa",
        OIDC_REDIRECT_URI: "http://127.0.0.1:53001/auth/callback",
        TRUSTED_HOSTS: '["127.0.0.1","localhost"]',
      },
    },
    {
      command: "pnpm --filter @fusion-helpdesk/web dev --port 53001",
      url: "http://127.0.0.1:53001",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_URL: "http://127.0.0.1:58011" },
    },
  ],
});
