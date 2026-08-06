import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { humanizeCode, OutcomeBadge, outcomeTone } from "./Admin";

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
