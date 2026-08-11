import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ActiveBadge,
  CodeChips,
  humanizeCode,
  OutcomeBadge,
  outcomeTone,
} from "./Admin";

describe("humanizeCode", () => {
  it("turns event codes into readable labels", () => {
    expect(humanizeCode("TICKET_TRANSITIONED")).toBe("Ticket transitioned");
    expect(humanizeCode("AUTHORIZATION_DENIED")).toBe("Authorization denied");
    expect(humanizeCode("AI_TOOL_CALL_RECORDED")).toBe("AI tool call recorded");
  });
});

describe("outcomeTone", () => {
  it("maps outcome and decision codes to badge tones", () => {
    expect(outcomeTone("SUCCESS")).toBe("success");
    expect(outcomeTone("ALLOWED")).toBe("success");
    expect(outcomeTone("DENIED")).toBe("danger");
    expect(outcomeTone("FAILED")).toBe("danger");
    expect(outcomeTone("PARTIAL")).toBe("warning");
    expect(outcomeTone("UNKNOWN_CODE")).toBe("neutral");
  });
});

describe("OutcomeBadge", () => {
  it("renders the humanized outcome with its tone class", () => {
    render(<OutcomeBadge code="DENIED" />);
    const badge = screen.getByText("Denied");
    expect(badge.className).toContain("outcome-badge--danger");
  });
});

describe("ActiveBadge", () => {
  it("renders active accounts with the success tone", () => {
    render(<ActiveBadge active />);
    const badge = screen.getByText("Active");
    expect(badge.className).toContain("outcome-badge--success");
  });

  it("renders inactive accounts with the neutral tone", () => {
    render(<ActiveBadge active={false} />);
    const badge = screen.getByText("Inactive");
    expect(badge.className).toContain("outcome-badge--neutral");
  });
});

describe("CodeChips", () => {
  it("renders humanized chips for each code", () => {
    render(
      <CodeChips codes={["PLATFORM_ADMIN", "SERVICE_AGENT"]} label="Roles" />,
    );
    const list = screen.getByRole("list", { name: "Roles" });
    expect(list).toBeDefined();
    expect(screen.getByText("Platform admin")).toBeDefined();
    expect(screen.getByText("Service agent")).toBeDefined();
  });

  it("renders a placeholder when there are no codes", () => {
    render(<CodeChips codes={[]} label="Roles" />);
    expect(screen.getByText("—")).toBeDefined();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
