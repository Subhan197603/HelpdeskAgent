import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const TYPE_LABELS: Record<string, string> = {
  FAQ: "FAQ",
  API_REFERENCE: "API reference",
};

export function documentTypeLabel(code: string): string {
  const special = TYPE_LABELS[code];
  if (special) return special;
  const words = code.toLowerCase().split("_");
  const first = words[0] ?? "";
  return [
    first.charAt(0).toUpperCase() + first.slice(1),
    ...words.slice(1),
  ].join(" ");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function highlightMatches(text: string, query: string): ReactNode {
  const terms = query
    .split(/\s+/)
    .map((term) => term.trim())
    .filter((term) => term.length > 1);
  if (terms.length === 0) return text;
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  if (parts.length === 1) return text;
  const lowered = terms.map((term) => term.toLowerCase());
  return parts.map((part, index) =>
    lowered.includes(part.toLowerCase()) ? (
      <mark key={index}>{part}</mark>
    ) : (
      part
    ),
  );
}

export interface EvidenceChunk {
  rank: number;
  document_id: string;
  document_title: string;
  document_type: string | null;
  section_title: string | null;
  section_anchor: string | null;
  content: string;
  final_score: number;
}

export interface EvidenceGroup {
  top: EvidenceChunk;
  matchCount: number;
}

export function groupEvidenceByDocument(
  evidence: readonly EvidenceChunk[],
): readonly EvidenceGroup[] {
  const groups = new Map<string, EvidenceGroup>();
  const ordered = [...evidence].sort((left, right) => left.rank - right.rank);
  for (const chunk of ordered) {
    const existing = groups.get(chunk.document_id);
    if (existing) {
      existing.matchCount += 1;
    } else {
      groups.set(chunk.document_id, { top: chunk, matchCount: 1 });
    }
  }
  return [...groups.values()];
}

export function ArticleCard({
  documentType,
  excerpt,
  href,
  meta,
  title,
}: {
  documentType: string;
  excerpt: string | null;
  href: string;
  meta?: string;
  title: string;
}) {
  return (
    <article className="article-card">
      <div className="article-card__heading">
        <h3>
          <Link to={href}>{title}</Link>
        </h3>
        <span className="article-card__type">
          {documentTypeLabel(documentType)}
        </span>
      </div>
      {excerpt ? <p className="article-card__excerpt">{excerpt}</p> : null}
      {meta ? <p className="article-card__meta">{meta}</p> : null}
    </article>
  );
}
