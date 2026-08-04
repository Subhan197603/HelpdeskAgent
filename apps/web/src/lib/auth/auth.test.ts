import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { challengeS256, generateVerifier } from "./pkce";
import {
  __resetAuthForTests,
  beginLogin,
  completeLogin,
  getAccessToken,
  clearTokens,
  sanitizeReturnTo,
  type AuthConfiguration,
} from "./oidc";

const config: AuthConfiguration = {
  oidc_enabled: true,
  issuer_url: "https://idp.example.test",
  client_id: "spa-client",
  audience: "helpdesk-api",
  redirect_uri: "https://app.example.test/auth/callback",
  scopes: "openid profile email",
  developer_identity_enabled: false,
};

const discovery = {
  issuer: "https://idp.example.test",
  authorization_endpoint: "https://idp.example.test/authorize",
  token_endpoint: "https://idp.example.test/token",
  jwks_uri: "https://idp.example.test/jwks",
};

beforeEach(() => {
  sessionStorage.clear();
  __resetAuthForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PKCE", () => {
  it("computes the RFC 7636 S256 challenge for the reference verifier", async () => {
    await expect(
      challengeS256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ).resolves.toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("generates unique, URL-safe, spec-length verifiers", () => {
    const first = generateVerifier();
    const second = generateVerifier();
    expect(first).not.toBe(second);
    expect(first.length).toBeGreaterThanOrEqual(43);
    expect(first.length).toBeLessThanOrEqual(128);
    expect(first).toMatch(/^[A-Za-z0-9\-._~]+$/);
  });
});

describe("return-to sanitisation", () => {
  it("keeps same-origin relative paths", () => {
    expect(sanitizeReturnTo("/portal/requests/BI-1")).toBe(
      "/portal/requests/BI-1",
    );
  });

  it.each([
    null,
    "",
    "https://evil.example.test/",
    "//evil.example.test/path",
    "javascript:alert(1)",
    "portal/no-leading-slash",
    "/\\evil.example.test",
  ])("rejects unsafe value %s", (value) => {
    expect(sanitizeReturnTo(value)).toBe("/");
  });
});

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function storageValues(storage: Storage): string {
  const values: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key !== null) values.push(storage.getItem(key) ?? "");
  }
  return values.join(" ");
}

describe("login begin and callback", () => {
  it("redirects to the authorize endpoint with PKCE, state, and nonce", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(discovery), { status: 200 }),
        ),
      ),
    );

    await beginLogin(config, "/portal/requests");

    expect(assign).toHaveBeenCalledTimes(1);
    const target = new URL(String(assign.mock.calls.at(0)?.[0]));
    expect(target.origin).toBe("https://idp.example.test");
    expect(target.pathname).toBe("/authorize");
    expect(target.searchParams.get("response_type")).toBe("code");
    expect(target.searchParams.get("client_id")).toBe("spa-client");
    expect(target.searchParams.get("redirect_uri")).toBe(config.redirect_uri);
    expect(target.searchParams.get("code_challenge_method")).toBe("S256");
    expect(target.searchParams.get("code_challenge")).toBeTruthy();
    expect(target.searchParams.get("state")).toBeTruthy();
    expect(target.searchParams.get("nonce")).toBeTruthy();
    expect(target.searchParams.get("scope")).toBe("openid profile email");
  });

  it("rejects a callback whose state does not match the handshake", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(discovery), { status: 200 }),
        ),
      ),
    );
    await beginLogin(config, "/");

    await expect(
      completeLogin(
        config,
        new URLSearchParams({ code: "abc", state: "forged" }),
      ),
    ).rejects.toThrow(/state/i);
    expect(getAccessToken()).toBeNull();
  });

  it("exchanges the code with the verifier and stores the token in memory only", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });
    const fetchMock = vi.fn(
      (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        void init;
        const url = urlOf(input);
        if (url.includes("openid-configuration"))
          return Promise.resolve(
            new Response(JSON.stringify(discovery), { status: 200 }),
          );
        if (url === discovery.token_endpoint)
          return Promise.resolve(
            new Response(
              JSON.stringify({
                access_token: "test-access-token",
                token_type: "Bearer",
                expires_in: 300,
              }),
              { status: 200 },
            ),
          );
        throw new Error(`Unexpected fetch: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    await beginLogin(config, "/agent/tickets");
    const authorize = new URL(String(assign.mock.calls.at(0)?.[0]));
    const state = authorize.searchParams.get("state") ?? "";

    const outcome = await completeLogin(
      config,
      new URLSearchParams({ code: "auth-code", state }),
    );

    expect(outcome.returnTo).toBe("/agent/tickets");
    expect(getAccessToken()).toBe("test-access-token");
    const tokenCall = fetchMock.mock.calls.find(
      ([input]) => urlOf(input) === discovery.token_endpoint,
    );
    const body = tokenCall?.[1]?.body;
    expect(typeof body).toBe("string");
    expect(body).toContain("grant_type=authorization_code");
    expect(body).toContain("code_verifier=");
    expect(body).not.toContain("client_secret");
    expect(storageValues(localStorage)).not.toContain("test-access-token");
    expect(storageValues(sessionStorage)).not.toContain("test-access-token");
  });

  it("clears tokens on demand", () => {
    clearTokens();
    expect(getAccessToken()).toBeNull();
  });
});
