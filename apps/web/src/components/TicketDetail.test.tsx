import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AttachmentList,
  headlineSla,
  slaPresentation,
  TransitionMenu,
} from "./TicketDetail";

const base = {
  definition_code: "RESOLUTION",
  state_code: "RUNNING",
  target_at: "2026-08-05T18:00:00Z",
  remaining_working_seconds: 5400,
  paused_at: null,
  breached_at: null,
  completed_at: null,
};

describe("sla presentation rules", () => {
  it("classifies breached, met, paused, and running objectives", () => {
    expect(
      slaPresentation({ ...base, breached_at: "2026-08-05T10:00:00Z" }).label,
    ).toBe("Breached");
    expect(
      slaPresentation({
        ...base,
        state_code: "COMPLETED",
        completed_at: "2026-08-05T10:00:00Z",
      }).label,
    ).toBe("Met");
    expect(
      slaPresentation({ ...base, paused_at: "2026-08-05T10:00:00Z" }).label,
    ).toBe("Paused");
    const running = slaPresentation(base);
    expect(running.label).toBe("Running");
    expect(running.detail).toContain("1h 30m");
  });

  it("selects the most urgent objective for the header chip", () => {
    const breached = { ...base, breached_at: "2026-08-05T10:00:00Z" };
    const met = {
      ...base,
      state_code: "COMPLETED",
      completed_at: "2026-08-05T10:00:00Z",
    };
    expect(headlineSla([met, breached])).toBe(breached);
    expect(headlineSla([met])).toBe(met);
    expect(headlineSla([])).toBeNull();
  });
});

describe("attachment list", () => {
  const item = (overrides: Partial<Record<string, unknown>>) => ({
    id: "a1",
    filename: "file.pdf",
    content_type: "application/pdf",
    size_bytes: 1234,
    scan_status: "CLEAN",
    visibility: "PUBLIC",
    uploaded_by_name: "Development Agent",
    created_at: "2026-08-05T10:00:00Z",
    ...overrides,
  });

  it("offers download only for clean attachments", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(
      <AttachmentList
        items={[
          item({ id: "a1", filename: "clean.pdf", scan_status: "CLEAN" }),
          item({ id: "a2", filename: "bad.txt", scan_status: "INFECTED" }),
          item({ id: "a3", filename: "wip.png", scan_status: "PENDING" }),
        ]}
        onDownload={onDownload}
      />,
    );
    expect(screen.getAllByRole("button", { name: /download/i })).toHaveLength(
      1,
    );
    await user.click(screen.getByRole("button", { name: /download/i }));
    expect(onDownload).toHaveBeenCalledWith("a1");
    expect(screen.getByLabelText("Status: INFECTED")).toBeVisible();
    expect(screen.getByLabelText("Status: PENDING")).toBeVisible();
  });

  it("renders an explicit empty state", () => {
    render(<AttachmentList items={[]} onDownload={vi.fn()} />);
    expect(screen.getByText(/No attachments yet/)).toBeVisible();
  });
});

describe("transition menu", () => {
  it("renders only server-provided transitions and reports the chosen code", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <TransitionMenu
        onSelect={onSelect}
        pending={false}
        transitions={[
          {
            code: "START_PROGRESS",
            name: "Start progress",
            to_status: "IN_PROGRESS",
            to_status_name: "In Progress",
          },
        ]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Change status" }));
    const option = screen.getByRole("menuitem", { name: /Start progress/ });
    await user.click(option);
    expect(onSelect).toHaveBeenCalledWith("START_PROGRESS");
    expect(screen.queryByRole("menuitem", { name: /Resolve/ })).toBeNull();
  });
});
