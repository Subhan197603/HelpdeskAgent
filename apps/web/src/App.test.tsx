import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "@fusion-helpdesk/api-client";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { DynamicField, LoginPage } from "./App";
import { ErrorSummary } from "./components/StatusPanel";
import { ApiProblem } from "./lib/api";
import { SessionProvider } from "./lib/session";

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
    const user = userEvent.setup();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <SessionProvider>
          <MemoryRouter>
            <LoginPage />
          </MemoryRouter>
        </SessionProvider>
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("button", { name: /continue as analyst/i }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: /continue as employee/i }),
    );
    expect(localStorage.getItem("fusion-helpdesk-session")).toContain(
      "DEV/customer",
    );
  });
});
