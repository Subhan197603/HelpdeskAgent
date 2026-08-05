import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import {
  ArticleCard,
  documentTypeLabel,
  groupEvidenceByDocument,
  highlightMatches,
} from "./Knowledge";

const evidence = (rank: number, documentId: string, section: string) => ({
  rank,
  document_id: documentId,
  document_title: `Document ${documentId}`,
  document_type: "FAQ",
  section_title: section,
  section_anchor: null,
  content: "Passwords expire every 90 days.",
  final_score: 1 / rank,
});

describe("documentTypeLabel", () => {
  it("humanizes document type codes", () => {
    expect(documentTypeLabel("USER_GUIDE")).toBe("User guide");
    expect(documentTypeLabel("FAQ")).toBe("FAQ");
    expect(documentTypeLabel("API_REFERENCE")).toBe("API reference");
    expect(documentTypeLabel("KNOWLEDGE_ARTICLE")).toBe("Knowledge article");
  });
});

describe("highlightMatches", () => {
  it("wraps each matching term in a mark element", () => {
    render(
      <p>
        {highlightMatches("Reset your Fusion password now", "fusion password")}
      </p>,
    );
    expect(
      screen.getByText("Fusion", { selector: "mark" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("password", { selector: "mark" }),
    ).toBeInTheDocument();
  });

  it("returns the plain text when nothing matches", () => {
    const { container } = render(
      <p>{highlightMatches("No overlap here", "zzz")}</p>,
    );
    expect(container.querySelectorAll("mark")).toHaveLength(0);
    expect(container.textContent).toBe("No overlap here");
  });

  it("treats regex metacharacters as literal text", () => {
    const { container } = render(
      <p>
        {highlightMatches("Error (ORA-600) in c++ module", "(ora-600) c++")}
      </p>,
    );
    expect(container.querySelectorAll("mark").length).toBeGreaterThan(0);
    expect(container.textContent).toBe("Error (ORA-600) in c++ module");
  });
});

describe("groupEvidenceByDocument", () => {
  it("keeps the best-ranked chunk per document and counts additional matches", () => {
    const groups = groupEvidenceByDocument([
      evidence(1, "a", "Intro"),
      evidence(2, "b", "Setup"),
      evidence(3, "a", "Deep dive"),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]?.top.section_title).toBe("Intro");
    expect(groups[0]?.matchCount).toBe(2);
    expect(groups[1]?.top.document_id).toBe("b");
    expect(groups[1]?.matchCount).toBe(1);
  });
});

describe("ArticleCard", () => {
  it("links to the article and shows the humanized type", () => {
    render(
      <MemoryRouter>
        <ArticleCard
          href="/portal/knowledge/articles/abc"
          title="Password reset guide"
          documentType="USER_GUIDE"
          excerpt="Step-by-step guide to resolve login problems."
          meta="IT Handbook"
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("link", { name: "Password reset guide" }),
    ).toHaveAttribute("href", "/portal/knowledge/articles/abc");
    expect(screen.getByText("User guide")).toBeInTheDocument();
    expect(
      screen.getByText("Step-by-step guide to resolve login problems."),
    ).toBeInTheDocument();
  });
});
