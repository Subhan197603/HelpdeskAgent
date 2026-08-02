type Tone = "danger" | "info" | "neutral" | "success" | "warning";

function Badge({
  children,
  label,
  tone,
}: {
  children: string;
  label: string;
  tone: Tone;
}) {
  return (
    <span
      aria-label={`${label}: ${children}`}
      className={`badge badge--${tone}`}
    >
      <span aria-hidden="true" className="badge__dot" />
      {children}
    </span>
  );
}

function statusTone(status: string): Tone {
  const value = status.toUpperCase().replaceAll(" ", "_");
  if (["RESOLVED", "CLOSED", "COMPLETED", "CLEAN"].includes(value))
    return "success";
  if (["FAILED", "BREACHED", "INFECTED", "REJECTED"].includes(value))
    return "danger";
  if (
    ["WAITING_FOR_CUSTOMER", "ON_HOLD", "QUARANTINED", "PENDING"].includes(
      value,
    )
  )
    return "warning";
  if (["NEW", "IN_PROGRESS", "SCANNING"].includes(value)) return "info";
  return "neutral";
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge label="Status" tone={statusTone(status)}>
      {status.replaceAll("_", " ")}
    </Badge>
  );
}

export function PriorityBadge({ priority }: { priority: string }) {
  const value = priority.toUpperCase();
  const tone: Tone =
    value === "P1" || value === "CRITICAL"
      ? "danger"
      : value === "P2" || value === "HIGH"
        ? "warning"
        : value === "P3" || value === "MEDIUM"
          ? "info"
          : "neutral";
  return (
    <Badge label="Priority" tone={tone}>
      {priority}
    </Badge>
  );
}

export function SlaBadge({
  label,
  state,
}: {
  label: string;
  state: "breached" | "met" | "paused" | "running";
}) {
  const tone: Tone =
    state === "breached"
      ? "danger"
      : state === "met"
        ? "success"
        : state === "paused"
          ? "warning"
          : "info";
  return (
    <Badge label="SLA" tone={tone}>
      {label}
    </Badge>
  );
}

export function HealthIndicator({
  label,
  healthy,
}: {
  label: string;
  healthy: boolean;
}) {
  return (
    <Badge label="Health" tone={healthy ? "success" : "danger"}>
      {label}
    </Badge>
  );
}

export function TrendIndicator({
  direction,
  value,
}: {
  direction: "down" | "flat" | "up";
  value: string;
}) {
  return (
    <span className={`trend trend--${direction}`}>
      <span aria-hidden="true">
        {direction === "up" ? "↑" : direction === "down" ? "↓" : "→"}
      </span>{" "}
      {value}
    </span>
  );
}
