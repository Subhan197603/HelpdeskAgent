import { useEffect, useRef, useState } from "react";

import { StatusBadge } from "./Badges";
import { Button } from "./Button";

export interface TicketSla {
  breached_at: string | null;
  completed_at: string | null;
  definition_code: string;
  paused_at: string | null;
  remaining_working_seconds: number | null;
  state_code: string;
  target_at: string | null;
}

export type SlaTone = "danger" | "info" | "success" | "warning";

export interface SlaPresentation {
  detail: string;
  label: "Breached" | "Met" | "Paused" | "Running";
  tone: SlaTone;
}

function formatRemaining(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours === 0) return `${String(minutes)}m`;
  return `${String(hours)}h ${String(minutes)}m`;
}

function formatMoment(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export function slaPresentation(sla: TicketSla): SlaPresentation {
  if (sla.breached_at !== null) {
    return {
      detail: `Breached ${formatMoment(sla.breached_at)}`,
      label: "Breached",
      tone: "danger",
    };
  }
  if (sla.completed_at !== null) {
    return {
      detail: `Met ${formatMoment(sla.completed_at)}`,
      label: "Met",
      tone: "success",
    };
  }
  if (sla.paused_at !== null) {
    return {
      detail: `Paused — target ${formatMoment(sla.target_at)}`,
      label: "Paused",
      tone: "warning",
    };
  }
  const remaining =
    sla.remaining_working_seconds === null
      ? `target ${formatMoment(sla.target_at)}`
      : `${formatRemaining(sla.remaining_working_seconds)} left`;
  return { detail: remaining, label: "Running", tone: "info" };
}

const URGENCY: Record<SlaPresentation["label"], number> = {
  Breached: 0,
  Running: 1,
  Paused: 2,
  Met: 3,
};

export function headlineSla(slas: readonly TicketSla[]): TicketSla | null {
  if (slas.length === 0) return null;
  return (
    [...slas].sort(
      (first, second) =>
        URGENCY[slaPresentation(first).label] -
        URGENCY[slaPresentation(second).label],
    )[0] ?? null
  );
}

export interface AttachmentItem {
  content_type: string;
  created_at: string;
  filename: string;
  id: string;
  scan_status: string;
  size_bytes: number;
  uploaded_by_name: string | null;
  visibility: string;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${String(bytes)} B`;
}

export function AttachmentList({
  items,
  onDownload,
}: {
  items: readonly AttachmentItem[];
  onDownload: (id: string) => void;
}) {
  if (items.length === 0)
    return <p className="donut-empty">No attachments yet.</p>;
  return (
    <ul className="attachment-list">
      {items.map((item) => (
        <li key={item.id}>
          <div className="attachment-list__meta">
            <strong>{item.filename}</strong>
            <small>
              {formatSize(item.size_bytes)}
              {item.uploaded_by_name
                ? ` · ${item.uploaded_by_name}`
                : ""} · {new Date(item.created_at).toLocaleString()}
            </small>
          </div>
          <StatusBadge size="sm" status={item.scan_status} />
          {item.scan_status === "CLEAN" && (
            <Button
              onClick={() => {
                onDownload(item.id);
              }}
              variant="secondary"
            >
              Download
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export interface TransitionOption {
  code: string;
  name: string;
  to_status: string;
  to_status_name: string;
}

export function TransitionMenu({
  onSelect,
  pending,
  transitions,
}: {
  onSelect: (code: string) => void;
  pending: boolean;
  transitions: readonly TransitionOption[];
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (eventObject: MouseEvent) => {
      if (!containerRef.current?.contains(eventObject.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("mousedown", close);
    };
  }, [open]);
  if (transitions.length === 0) return null;
  return (
    <div className="transition-menu" ref={containerRef}>
      <Button
        disabled={pending}
        onClick={() => {
          setOpen((value) => !value);
        }}
        variant="secondary"
      >
        {pending ? "Updating…" : "Change status"}
      </Button>
      {open && (
        <ul className="transition-menu__list" role="menu">
          {transitions.map((transition) => (
            <li key={transition.code} role="none">
              <button
                onClick={() => {
                  setOpen(false);
                  onSelect(transition.code);
                }}
                role="menuitem"
                type="button"
              >
                {transition.name}
                <small>→ {transition.to_status_name}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
