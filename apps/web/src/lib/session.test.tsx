import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider, useSession } from "./session";

function stubConfiguration(developerIdentityEnabled: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            oidc_enabled: false,
            issuer_url: null,
            client_id: null,
            audience: null,
            redirect_uri: null,
            scopes: "openid profile email",
            developer_identity_enabled: developerIdentityEnabled,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    ),
  );
}

function Probe() {
  const { session } = useSession();
  return <p>{session ? `mode:${session.mode}` : "signed-out"}</p>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("stored developer sessions against server truth", () => {
  it("keeps the developer session while the server allows developer identity", async () => {
    localStorage.setItem(
      "fusion-helpdesk-session",
      JSON.stringify({ identity: "DEV/customer", persona: "employee" }),
    );
    stubConfiguration(true);
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    expect(await screen.findByText("mode:developer")).toBeVisible();
  });

  it("signs out a stale developer session when the server has disabled developer identity", async () => {
    localStorage.setItem(
      "fusion-helpdesk-session",
      JSON.stringify({ identity: "DEV/customer", persona: "employee" }),
    );
    stubConfiguration(false);
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    expect(await screen.findByText("signed-out")).toBeVisible();
    expect(localStorage.getItem("fusion-helpdesk-session")).toBeNull();
  });
});
