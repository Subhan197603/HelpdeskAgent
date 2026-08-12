import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ActiveBadge,
  aiSafetyPresentation,
  CodeChips,
  formatEstimatedCost,
  formatTokenCount,
  humanizeCode,
  OutcomeBadge,
  outcomeTone,
} from "./Admin";

describe("AI governance presentation", () => {
  it("keeps distinct safety reasons and tones", () => {
    expect(aiSafetyPresentation("platform_disabled")).toEqual({
      label: "Platform disabled",
      tone: "danger",
    });
    expect(aiSafetyPresentation("budget_hard_stop").label).toBe(
      "Budget hard stop",
    );
    expect(aiSafetyPresentation("circuit_open").label).toContain(
      "current process",
    );
    expect(aiSafetyPresentation("ready_to_attempt").tone).toBe("success");
  });

  it("formats stored usage without inventing precision", () => {
    expect(formatTokenCount(1234)).toMatch(/1.234|1,234/);
    expect(formatEstimatedCost("8.5", "USD")).toContain("8.50");
    expect(formatEstimatedCost("not-a-number", "USD")).toBe("—");
  });
});

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
