const SPECIAL_WORDS: Record<string, string> = {
  ai: "AI",
  api: "API",
  oidc: "OIDC",
  sla: "SLA",
  jit: "JIT",
};

export function humanizeCode(code: string): string {
  const words = code.toLowerCase().split("_");
  return words
    .map((word, index) => {
      const special = SPECIAL_WORDS[word];
      if (special) return special;
      if (index === 0) return word.charAt(0).toUpperCase() + word.slice(1);
      return word;
    })
    .join(" ");
}

export type OutcomeToneName = "danger" | "neutral" | "success" | "warning";

const TONES: Record<string, OutcomeToneName> = {
  SUCCESS: "success",
  ALLOWED: "success",
  DENIED: "danger",
  FAILED: "danger",
  PARTIAL: "warning",
};

export function outcomeTone(code: string): OutcomeToneName {
  return TONES[code] ?? "neutral";
}

export function OutcomeBadge({ code }: { code: string }) {
  return (
    <span className={`outcome-badge outcome-badge--${outcomeTone(code)}`}>
      {humanizeCode(code)}
    </span>
  );
}

export function ActiveBadge({ active }: { active: boolean }) {
  return (
    <span
      className={`outcome-badge outcome-badge--${active ? "success" : "neutral"}`}
    >
      {active ? "Active" : "Inactive"}
    </span>
  );
}

export function CodeChips({
  codes,
  label,
}: {
  codes: string[];
  label: string;
}) {
  if (codes.length === 0) return <span className="code-chips-empty">—</span>;
  return (
    <ul aria-label={label} className="code-chips">
      {codes.map((code) => (
        <li key={code}>{humanizeCode(code)}</li>
      ))}
    </ul>
  );
}
