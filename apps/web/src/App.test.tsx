import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "@fusion-helpdesk/api-client";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  corpusBlockerLabel,
  corpusFindingPresentation,
  DynamicField,
  insertCannedResponse,
  LoginPage,
  sourceChangePresentation,
  sourceRefreshActions,
  sourceRefreshPresentation,
  sourceRefreshRunnable,
  ticketClassificationDisplay,
  watchActionLabel,
} from "./App";
import { ErrorSummary } from "./components/States";
import { ApiProblem } from "./lib/api";
import type { AuthConfiguration } from "./lib/auth/oidc";
import { SessionProvider } from "./lib/session";

function stubAuthConfiguration(overrides: Partial<AuthConfiguration> = {}) {
  const configuration: AuthConfiguration = {
    oidc_enabled: false,
    issuer_url: null,
    client_id: null,
    audience: null,
    redirect_uri: null,
    scopes: "openid profile email",
    developer_identity_enabled: true,
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(configuration), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    ),
  );
}

function renderLogin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

type FormField = components["schemas"]["FormFieldResponse"];

function field(overrides: Partial<FormField> = {}): FormField {
  return {
    condition: null,
    data_type: "TEXT",
    description: null,
    display_order: 10,
    field_code: "summary",
    field_id: "34000000-0000-0000-0000-000000000001",
    label: "Brief summary",
    options: [],
    required: true,
    validation: {
      maximum: null,
      maximum_length: 200,
      minimum: null,
      minimum_length: 5,
      pattern: null,
    },
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dynamic request fields", () => {
  it("renders published labels, help text, options, and required state", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <DynamicField
        field={field({
          data_type: "SINGLE_SELECT",
          description: "Select the affected environment.",
          field_code: "environment",
          label: "Affected environment",
          options: [
            {
              display_order: 10,
              id: "34100000-0000-0000-0000-000000000001",
              label: "Production",
              value: "PROD",
            },
          ],
        })}
        onChange={onChange}
        value=""
      />,
    );

    const select = screen.getByRole("combobox", {
      name: /affected environment/i,
    });
    expect(select).toBeRequired();
    expect(select).toHaveAccessibleDescription(
      "Select the affected environment.",
    );
    await user.selectOptions(select, "PROD");
    expect(onChange).toHaveBeenCalledWith("PROD");
  });

  it("supports boolean fields without hard-coded request-specific markup", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <DynamicField
        field={field({
          data_type: "BOOLEAN",
          field_code: "business_critical",
          label: "Business critical",
        })}
        onChange={onChange}
        value={false}
      />,
    );

    await user.click(
      screen.getByRole("checkbox", { name: /business critical/i }),
    );
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("portal state handling", () => {
  it.each([
    ["both values", "MODERATE", "HIGH", ["MODERATE", "HIGH"]],
    ["missing impact", null, "HIGH", ["Not provided", "HIGH"]],
    ["missing urgency", "MODERATE", null, ["MODERATE", "Not provided"]],
    ["both missing", null, null, ["Not provided", "Not provided"]],
  ])(
    "presents ticket classification honestly when %s",
    (_case, impact, urgency, expected) => {
      expect([
        ticketClassificationDisplay(impact),
        ticketClassificationDisplay(urgency),
      ]).toEqual(expected);
    },
  );

  it("announces conflict responses with recovery guidance", () => {
    render(
      <ErrorSummary
        error={
          new ApiProblem(
            409,
            "This draft changed. Reload it before saving again.",
          )
        }
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your information is out of date",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Reload it");
  });

  it("offers both development personas and enters the employee portal", async () => {
    stubAuthConfiguration({ developer_identity_enabled: true });
    const user = userEvent.setup();
    renderLogin();

    expect(
      await screen.findByRole("button", { name: /continue as analyst/i }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: /continue as employee/i }),
    );
    expect(localStorage.getItem("fusion-helpdesk-session")).toContain(
      "DEV/customer",
    );
  });
});

describe("personal canned response insertion", () => {
  it("creates editable draft text without changing any other comment state", () => {
    expect(insertCannedResponse("", "Please provide the invoice number.")).toBe(
      "Please provide the invoice number.",
    );
    expect(
      insertCannedResponse("Hello,", "Please provide the invoice number."),
    ).toBe("Hello,\n\nPlease provide the invoice number.");
  });
});

describe("personal ticket watchlist state", () => {
  it("labels idempotent watch and unwatch actions without implying notifications", () => {
    expect(watchActionLabel(false, false)).toBe("Watch");
    expect(watchActionLabel(true, false)).toBe("Unwatch");
    expect(watchActionLabel(false, true)).toBe("Watching…");
    expect(watchActionLabel(true, true)).toBe("Unwatching…");
  });
});

describe("knowledge source refresh lifecycle presentation", () => {
  it("maps every effective refresh state to a deterministic badge and label", () => {
    expect(sourceRefreshPresentation("CURRENT")).toEqual({
      code: "SUCCESS",
      label: "Current",
    });
    expect(sourceRefreshPresentation("REFRESH_DUE")).toEqual({
      code: "PARTIAL",
      label: "Refresh due",
    });
    expect(sourceRefreshPresentation("REFRESHING")).toEqual({
      code: "PARTIAL",
      label: "Refreshing",
    });
    expect(sourceRefreshPresentation("STALE")).toEqual({
      code: "DENIED",
      label: "Stale",
    });
    expect(sourceRefreshPresentation("RETIRED")).toEqual({
      code: "DENIED",
      label: "Retired",
    });
  });

  it("offers admin transitions only from administrable states", () => {
    expect(sourceRefreshActions("CURRENT")).toEqual([
      "MARK_REFRESH_DUE",
      "MARK_STALE",
    ]);
    expect(sourceRefreshActions("REFRESH_DUE")).toEqual([
      "MARK_CURRENT",
      "MARK_STALE",
    ]);
    expect(sourceRefreshActions("STALE")).toEqual([
      "MARK_REFRESH_DUE",
      "MARK_CURRENT",
    ]);
    expect(sourceRefreshActions("REFRESHING")).toEqual([]);
    expect(sourceRefreshActions("RETIRED")).toEqual([]);
  });

  it("allows starting a refresh run only from settled states", () => {
    expect(sourceRefreshRunnable("CURRENT")).toBe(true);
    expect(sourceRefreshRunnable("REFRESH_DUE")).toBe(true);
    expect(sourceRefreshRunnable("STALE")).toBe(true);
    expect(sourceRefreshRunnable("REFRESHING")).toBe(false);
    expect(sourceRefreshRunnable("RETIRED")).toBe(false);
  });

  it("maps every page change classification to a deterministic badge", () => {
    expect(sourceChangePresentation("UNCHANGED", false)).toEqual({
      code: "SUCCESS",
      label: "Unchanged",
    });
    expect(sourceChangePresentation("CHANGED", false)).toEqual({
      code: "PARTIAL",
      label: "Changed",
    });
    expect(sourceChangePresentation("REDIRECTED", false)).toEqual({
      code: "PARTIAL",
      label: "Redirected",
    });
    expect(sourceChangePresentation("REMOVED", false)).toEqual({
      code: "DENIED",
      label: "Removed",
    });
    expect(sourceChangePresentation(null, true)).toEqual({
      code: "DENIED",
      label: "Failed",
    });
    expect(sourceChangePresentation(null, false)).toEqual({
      code: "PARTIAL",
      label: "Pending",
    });
  });

  it("maps every corpus validation finding type to a deterministic badge", () => {
    expect(corpusFindingPresentation("STRUCTURAL_DEFECT")).toEqual({
      code: "DENIED",
      label: "Structural defect",
    });
    expect(corpusFindingPresentation("EMPTY_CHUNK")).toEqual({
      code: "DENIED",
      label: "Empty chunk",
    });
    expect(corpusFindingPresentation("DUPLICATE_DOCUMENT")).toEqual({
      code: "PARTIAL",
      label: "Duplicate document",
    });
    expect(corpusFindingPresentation("NEAR_DUPLICATE_CHUNK")).toEqual({
      code: "PARTIAL",
      label: "Near-duplicate chunk",
    });
  });

  it("labels every corpus publication blocker deterministically", () => {
    expect(corpusBlockerLabel("NO_VALIDATION_RUN")).toBe("No validation run");
    expect(corpusBlockerLabel("VALIDATION_RUN_INCOMPLETE")).toBe(
      "Validation run incomplete",
    );
    expect(corpusBlockerLabel("VALIDATION_RUN_TRUNCATED")).toBe(
      "Validation run truncated",
    );
    expect(corpusBlockerLabel("VALIDATION_STALE")).toBe("Validation stale");
  });
});

describe("production sign-in modes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("shows only single sign-on when developer identity is disabled", async () => {
    stubAuthConfiguration({
      developer_identity_enabled: false,
      oidc_enabled: true,
      issuer_url: "https://idp.example.test",
      client_id: "spa-client",
      redirect_uri: "https://app.example.test/auth/callback",
    });
    renderLogin();

    expect(
      await screen.findByRole("button", { name: /sign in/i }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /continue as employee/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /continue as analyst/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/development identity mode/i)).toBeNull();
  });

  it("reports when no sign-in method is configured", async () => {
    stubAuthConfiguration({
      developer_identity_enabled: false,
      oidc_enabled: false,
    });
    renderLogin();

    expect(
      await screen.findByText(/no sign-in method is configured/i),
    ).toBeVisible();
  });
});
