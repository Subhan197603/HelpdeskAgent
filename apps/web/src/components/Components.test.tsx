import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Avatar } from "./Avatar";
import { PriorityBadge, StatusBadge } from "./Badges";
import { Button, IconButton } from "./Button";
import { SearchField } from "./SearchField";
import { Tabs } from "./Tabs";
import { AttachmentStatus } from "./AttachmentUploader";
import { DataTable, Pagination } from "./DataTable";
import { ConfirmationDialog, FormErrorSummary, TextInput } from "./Forms";
import {
  ConflictState,
  EmptyState,
  ErrorState,
  LoadingSkeleton,
  UnauthorizedState,
} from "./States";
import { TimelineEvent } from "./Tickets";

function renderWithQuery(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("shared UI states", () => {
  it("renders loading, empty, error, unauthorized, and conflict states accessibly", () => {
    render(
      <>
        <LoadingSkeleton />
        <EmptyState />
        <ErrorState />
        <UnauthorizedState />
        <ConflictState />
      </>,
    );
    expect(
      screen.getByRole("status", { name: "Loading content" }),
    ).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { name: "No results" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Something went wrong" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "You are not authorized" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Your information is out of date" }),
    ).toBeVisible();
  });

  it("renders two-letter initials with a deterministic tone", () => {
    const { container: first } = render(<Avatar name="UAT Customer" />);
    const { container: second } = render(<Avatar name="UAT Customer" />);
    const { container: single } = render(<Avatar name="Admin" size="sm" />);
    const one = first.querySelector(".avatar");
    const two = second.querySelector(".avatar");
    expect(one).toHaveTextContent("UC");
    expect(one?.className).toMatch(/avatar--tone-\d/);
    expect(one?.className).toBe(two?.className);
    expect(single.querySelector(".avatar")).toHaveTextContent("A");
    expect(single.querySelector(".avatar")?.className).toContain("avatar--sm");
  });

  it("supports a small badge size variant", () => {
    render(<StatusBadge size="sm" status="NEW" />);
    expect(screen.getByLabelText("Status: NEW").className).toContain(
      "badge--sm",
    );
  });

  it("renders text labels for status and priority variants", () => {
    render(
      <>
        <StatusBadge status="IN_PROGRESS" />
        <StatusBadge status="RESOLVED" />
        <PriorityBadge priority="P1" />
        <PriorityBadge priority="P4" />
      </>,
    );
    expect(screen.getByLabelText("Status: IN PROGRESS")).toBeVisible();
    expect(screen.getByLabelText("Status: RESOLVED")).toBeVisible();
    expect(screen.getByLabelText("Priority: P1")).toBeVisible();
    expect(screen.getByLabelText("Priority: P4")).toBeVisible();
  });
});

describe("shared design-system components", () => {
  it("renders button variants as buttons or router links", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    renderWithQuery(
      <>
        <Button onClick={onClick}>Save</Button>
        <Button to="/portal" variant="inverse">
          Portal
        </Button>
        <Button disabled variant="secondary">
          Waiting
        </Button>
      </>,
    );
    const save = screen.getByRole("button", { name: "Save" });
    expect(save.className).toContain("button primary");
    await user.click(save);
    expect(onClick).toHaveBeenCalledOnce();
    const link = screen.getByRole("link", { name: "Portal" });
    expect(link).toHaveAttribute("href", "/portal");
    expect(link.className).toContain("button--inverse");
    expect(screen.getByRole("button", { name: "Waiting" })).toBeDisabled();
  });

  it("requires an accessible label on icon buttons", () => {
    render(<IconButton icon="bell" label="Notifications" disabled />);
    const button = screen.getByRole("button", { name: "Notifications" });
    expect(button.className).toContain("icon-button");
    expect(button).toBeDisabled();
  });

  it("moves tab selection with arrow keys and marks selection", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Tabs
        activeId="a"
        items={[
          { badge: "ERP", id: "a", label: "Oracle ERP" },
          { badge: "HCM", id: "b", label: "Oracle HCM" },
        ]}
        label="Service projects"
        onChange={onChange}
      />,
    );
    const first = screen.getByRole("tab", { name: /Oracle ERP/ });
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Oracle HCM/ })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    first.focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("renders a labelled disabled search field with a shortcut hint", () => {
    render(
      <SearchField
        disabled
        hint="Ctrl K"
        label="Search tickets and services"
        placeholder="Search tickets and services…"
      />,
    );
    const input = screen.getByLabelText("Search tickets and services");
    expect(input).toBeDisabled();
    expect(screen.getByText("Ctrl K")).toBeInTheDocument();
  });
});

describe("shared tables and forms", () => {
  it("renders accessible headers and pagination behavior", async () => {
    const next = vi.fn();
    const previous = vi.fn();
    const user = userEvent.setup();
    renderWithQuery(
      <>
        <DataTable
          caption="Tickets"
          columns={[
            {
              header: "Ticket",
              key: "ticket",
              render: (row: { key: string }) => row.key,
            },
          ]}
          getRowKey={(row) => row.key}
          rows={[{ key: "ERP-1" }]}
        />
        <Pagination hasNext onNext={next} onPrevious={previous} page={1} />
      </>,
    );
    expect(screen.getByRole("columnheader", { name: "Ticket" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(next).toHaveBeenCalledOnce();
  });

  it("links validation summaries to fields", () => {
    render(
      <>
        <FormErrorSummary
          errors={[{ field: "summary", message: "Enter a summary" }]}
        />
        <TextInput error="Enter a summary" id="summary" label="Summary" />
      </>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a summary");
    expect(screen.getByLabelText("Summary")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("opens a modal confirmation and supports cancellation", async () => {
    const cancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmationDialog
        onCancel={cancel}
        onConfirm={vi.fn()}
        open
        title="Confirm submission"
      >
        Review this request before submitting.
      </ConfirmationDialog>,
    );
    expect(
      screen.getByRole("dialog", { name: "Confirm submission" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledOnce();
  });
});

describe("ticket presentation", () => {
  it("presents public and internal timeline classifications as text", () => {
    render(
      <ol>
        <TimelineEvent
          actor="Sarah Customer"
          body="Public update"
          classification="PUBLIC"
          dateTime="2026-08-02T10:00:00Z"
          time="10:00"
        />
        <TimelineEvent
          actor="John Analyst"
          body="Internal note"
          classification="INTERNAL"
          dateTime="2026-08-02T10:05:00Z"
          time="10:05"
        />
      </ol>,
    );
    expect(screen.getByText("PUBLIC")).toBeVisible();
    expect(screen.getByText("INTERNAL")).toBeVisible();
  });

  it("renders attachment malware-scan states as text", () => {
    render(
      <>
        <AttachmentStatus filename="evidence.pdf" status="SCANNING" />
        <AttachmentStatus filename="clean.txt" status="CLEAN" />
      </>,
    );
    expect(screen.getByLabelText("Status: SCANNING")).toBeVisible();
    expect(screen.getByLabelText("Status: CLEAN")).toBeVisible();
  });
});
