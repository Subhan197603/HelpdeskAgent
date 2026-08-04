import { createHelpdeskClient } from "@fusion-helpdesk/api-client";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
});

function captureFetch() {
  const seen: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      seen.push(new Request(input, init));
      return Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
  return {
    first(): Request {
      const request = seen[0];
      if (!request) throw new Error("No request was captured.");
      return request;
    },
  };
}

describe("helpdesk client authentication modes", () => {
  it("bearer mode attaches Authorization and never the developer header", async () => {
    const requests = captureFetch();
    const client = createHelpdeskClient({
      baseUrl: "http://api.example.test",
      auth: { mode: "bearer", getToken: () => "bearer-token-value" },
    });
    await client.GET("/api/v1/me");
    expect(requests.first().headers.get("authorization")).toBe(
      "Bearer bearer-token-value",
    );
    expect(requests.first().headers.get("x-developer-user")).toBeNull();
  });

  it("bearer mode omits Authorization when no token is available", async () => {
    const requests = captureFetch();
    const client = createHelpdeskClient({
      baseUrl: "http://api.example.test",
      auth: { mode: "bearer", getToken: () => null },
    });
    await client.GET("/api/v1/me");
    expect(requests.first().headers.get("authorization")).toBeNull();
    expect(requests.first().headers.get("x-developer-user")).toBeNull();
  });

  it("developer mode keeps the existing header contract", async () => {
    const requests = captureFetch();
    const client = createHelpdeskClient({
      baseUrl: "http://api.example.test",
      identity: "DEV/customer",
    });
    await client.GET("/api/v1/me");
    expect(requests.first().headers.get("x-developer-user")).toBe(
      "DEV/customer",
    );
    expect(requests.first().headers.get("authorization")).toBeNull();
  });
});
