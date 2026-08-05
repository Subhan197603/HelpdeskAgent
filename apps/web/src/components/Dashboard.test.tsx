import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ActivityFeed, DonutChart, formatDelta } from "./Dashboard";

describe("dashboard delta formatting", () => {
  it("renders a percentage only when the previous value is positive", () => {
    expect(formatDelta(28, 24)).toBe("+17% from yesterday");
    expect(formatDelta(20, 25)).toBe("-20% from yesterday");
    expect(formatDelta(24, 24)).toBe("0% from yesterday");
  });

  it("falls back to absolute difference or no-comparison text", () => {
    expect(formatDelta(32, 0)).toBe("+32 — no prior comparison");
    expect(formatDelta(0, 0)).toBe("No prior comparison");
  });
});

describe("donut chart", () => {
  it("exposes slice data to assistive technology", () => {
    render(
      <DonutChart
        label="Tickets by status"
        slices={[
          { label: "New", value: 32 },
          { label: "In Progress", value: 45 },
        ]}
      />,
    );
    expect(
      screen.getByRole("img", { name: /Tickets by status/ }),
    ).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("42%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("58%").length).toBeGreaterThan(0);
  });

  it("renders an empty state when all slices are zero", () => {
    render(<DonutChart label="Tickets by status" slices={[]} />);
    expect(screen.getByText(/No data yet/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("activity feed", () => {
  it("lists events with ticket keys and machine-readable times", () => {
    render(
      <MemoryRouter>
        <ActivityFeed
          items={[
            {
              id: "event:1",
              ticket_key: "ERP-1",
              event_type: "STATUS_CHANGED",
              actor_name: "John Analyst",
              created_at: "2026-08-05T10:00:00Z",
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByText(/ERP-1/)).toBeInTheDocument();
    expect(document.querySelector("time")?.getAttribute("datetime")).toBe(
      "2026-08-05T10:00:00Z",
    );
  });
});
