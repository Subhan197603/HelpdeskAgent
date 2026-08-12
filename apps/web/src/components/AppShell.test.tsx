import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "../lib/session";
import { AppShell } from "./AppShell";

let permissions: string[] = [];

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    sessionApiClient: () => ({
      GET: () =>
        Promise.resolve({
          data: {
            authentication_mode: "developer_header",
            business_unit_id: null,
            business_unit_name: null,
            display_name: "Test User",
            permission_codes: permissions,
            provider_code: null,
            role_codes: [],
            support_group_ids: [],
            tenant_id: "10000000-0000-0000-0000-000000000001",
            user_id: "20000000-0000-0000-0000-000000000001",
          },
          response: new Response(null, { status: 200 }),
        }),
    }),
  };
});

function renderShell(path = "/portal") {
  localStorage.setItem(
    "fusion-helpdesk-session",
    JSON.stringify({ identity: "DEV/customer", persona: "employee" }),
  );
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SessionProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppShell>
            <h1>Page content</h1>
          </AppShell>
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

describe("application shell", () => {
  beforeEach(() => {
    localStorage.clear();
    permissions = [
      "CATALOG_PROJECT_LIST",
      "TICKET_DRAFT_CREATE",
      "TICKET_READ_OWN",
    ];
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
              developer_identity_enabled: true,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        ),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders active permission-aware navigation without analyst capabilities", async () => {
    renderShell("/portal/catalog");
    expect(
      await screen.findByRole("link", { name: "Browse services" }),
    ).toHaveClass("active");
    expect(
      screen.queryByRole("link", { name: "My queues" }),
    ).not.toBeInTheDocument();
  });

  it("reveals analyst navigation only when the backend grants permission", async () => {
    permissions.push("TICKET_ANALYST_READ");
    renderShell("/agent/tickets");
    expect(await screen.findByRole("link", { name: "My queues" })).toHaveClass(
      "active",
    );
  });

  it("marks the active navigation item for assistive technology", async () => {
    renderShell("/portal/catalog");
    expect(
      await screen.findByRole("link", { name: "Browse services" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("keeps accessible names and tooltips on collapsed navigation", async () => {
    localStorage.setItem("helpdesk-sidebar-collapsed", "true");
    renderShell("/portal");
    const home = await screen.findByRole("link", { name: "Home" });
    expect(home).toHaveAttribute("title", "Home");
    expect(home).toHaveAttribute("aria-label", "Home");
    expect(screen.getByRole("link", { name: "My tickets" })).toHaveAttribute(
      "title",
      "My tickets",
    );
  });

  it("shows the analyst navigation section only when permission is granted", async () => {
    renderShell("/portal");
    await screen.findByRole("link", { name: "Home" });
    expect(screen.queryByText("Analyst tools")).not.toBeInTheDocument();
  });

  it("groups analyst navigation without duplicate queue routes", async () => {
    permissions.push("TICKET_ANALYST_READ");
    renderShell("/agent/tickets");
    await screen.findByRole("link", { name: "My queues" });
    expect(screen.getByText("Analyst tools")).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "All tickets" }),
    ).not.toBeInTheDocument();
  });

  it("shows the dashboard link first for analysts and never for employees", async () => {
    renderShell("/portal");
    await screen.findByRole("link", { name: "Home" });
    expect(
      screen.queryByRole("link", { name: "Dashboard" }),
    ).not.toBeInTheDocument();
    permissions.push("TICKET_ANALYST_READ");
    renderShell("/agent/dashboard");
    const dashboard = await screen.findByRole("link", { name: "Dashboard" });
    expect(dashboard).toHaveAttribute("href", "/agent/dashboard");
    expect(dashboard).toHaveAttribute("aria-current", "page");
  });

  it("shows knowledge administration only with its dedicated permission", async () => {
    renderShell("/portal");
    await screen.findByRole("link", { name: "Home" });
    expect(
      screen.queryByRole("link", { name: /^Knowledge$/ }),
    ).not.toBeInTheDocument();
    permissions.push("KNOWLEDGE_DOCUMENT_READ_ADMIN");
    renderShell("/admin/knowledge");
    expect(
      await screen.findByRole("link", { name: /^Knowledge$/ }),
    ).toHaveAttribute("href", "/admin/knowledge");
  });

  it("persists sidebar collapse and supports the mobile drawer", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(
      await screen.findByRole("button", { name: "Collapse sidebar" }),
    );
    expect(localStorage.getItem("helpdesk-sidebar-collapsed")).toBe("true");
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByLabelText("Application navigation")).toHaveClass(
      "app-sidebar--open",
    );
    await user.keyboard("{Escape}");
    expect(screen.getByLabelText("Application navigation")).not.toHaveClass(
      "app-sidebar--open",
    );
  });
});
