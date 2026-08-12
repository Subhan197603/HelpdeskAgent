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

const ISO_DAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export function isoDayName(isoDayOfWeek: number): string {
  return ISO_DAY_NAMES[isoDayOfWeek - 1] ?? `Day ${String(isoDayOfWeek)}`;
}

export function formatMinutes(value: number | null | undefined): string {
  if (value == null) return "—";
  const days = Math.floor(value / 1440);
  const hours = Math.floor((value % 1440) / 60);
  const minutes = value % 60;
  const parts: string[] = [];
  if (days > 0) parts.push(`${String(days)}d`);
  if (hours > 0) parts.push(`${String(hours)}h`);
  if (minutes > 0 || parts.length === 0) parts.push(`${String(minutes)}m`);
  return parts.join(" ");
}

const AI_SAFETY_STATES: Record<
  string,
  { label: string; tone: OutcomeToneName }
> = {
  platform_disabled: { label: "Platform disabled", tone: "danger" },
  policy_unavailable: { label: "Policy unavailable", tone: "danger" },
  policy_disabled: { label: "Policy disabled", tone: "danger" },
  budget_hard_stop: { label: "Budget hard stop", tone: "danger" },
  provider_configuration_incomplete: {
    label: "Provider not deployed",
    tone: "warning",
  },
  retrieval_configuration_unavailable: {
    label: "Retrieval unavailable",
    tone: "warning",
  },
  circuit_open: { label: "Circuit open — current process", tone: "warning" },
  ready_to_attempt: { label: "Ready to attempt", tone: "success" },
};

export function aiSafetyPresentation(code: string) {
  return (
    AI_SAFETY_STATES[code] ?? {
      label: humanizeCode(code.toUpperCase()),
      tone: "neutral" as const,
    }
  );
}

export function formatTokenCount(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(
    value,
  );
}

export function formatEstimatedCost(
  value: string | number,
  currency: string,
): string {
  const amount = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat(undefined, {
      currency,
      maximumFractionDigits: 4,
      minimumFractionDigits: 2,
      style: "currency",
    }).format(amount);
  } catch {
    return `${amount.toFixed(4)} ${currency}`;
  }
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
