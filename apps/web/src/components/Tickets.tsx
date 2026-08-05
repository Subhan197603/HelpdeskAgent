import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Avatar } from "./Avatar";
import { PriorityBadge, StatusBadge } from "./Badges";
import { Button } from "./Button";
import { MetadataGrid } from "./Layout";

export function TicketListItem({
  href,
  metadata,
  priority,
  status,
  summary,
  ticketKey,
}: {
  href: string;
  metadata?: string;
  priority: string;
  status: string;
  summary: string;
  ticketKey: string;
}) {
  return (
    <Link className="ticket-list-item" to={href}>
      <span className="ticket-list-item__key">{ticketKey}</span>
      <span className="ticket-list-item__summary">
        <strong>{summary}</strong>
        {metadata && <small>{metadata}</small>}
      </span>
      <StatusBadge status={status} />
      <PriorityBadge priority={priority} />
    </Link>
  );
}

export function QueueRow(props: Parameters<typeof TicketListItem>[0]) {
  return <TicketListItem {...props} />;
}

export function TicketHeader({
  actions,
  priority,
  status,
  summary,
  ticketKey,
}: {
  actions?: ReactNode;
  priority: string;
  status: string;
  summary: string;
  ticketKey: string;
}) {
  return (
    <header className="ticket-header">
      <div>
        <div className="ticket-header__badges">
          <span className="ticket-key">{ticketKey}</span>
          <StatusBadge status={status} />
          <PriorityBadge priority={priority} />
        </div>
        <h1>{summary}</h1>
      </div>
      {actions && <div className="ticket-header__actions">{actions}</div>}
    </header>
  );
}

export function TicketMetadata({ items }: Parameters<typeof MetadataGrid>[0]) {
  return <MetadataGrid items={items} />;
}

export function TicketTimeline({
  children,
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  return (
    <section aria-labelledby="timeline-heading" className="ticket-timeline">
      <h2 id="timeline-heading">{title}</h2>
      <ol>{children}</ol>
    </section>
  );
}

export function TimelineEvent({
  actor,
  body,
  classification,
  dateTime,
  time,
}: {
  actor: string;
  body: string;
  classification?: string;
  dateTime: string;
  time: string;
}) {
  return (
    <li
      className={`timeline-event timeline-event--${classification?.toLowerCase() ?? "system"}`}
    >
      <span aria-hidden="true" className="timeline-event__marker" />
      <div>
        <header>
          <strong>{actor}</strong>
          {classification && (
            <span className="visibility">{classification}</span>
          )}
          <time dateTime={dateTime}>{time}</time>
        </header>
        <p>{body}</p>
      </div>
    </li>
  );
}

export function CommentComposer({
  analyst,
  body,
  disabled,
  onBodyChange,
  onSubmit,
  onVisibilityChange,
  visibility,
}: {
  analyst: boolean;
  body: string;
  disabled?: boolean;
  onBodyChange: (body: string) => void;
  onSubmit: () => void;
  onVisibilityChange?: (visibility: "INTERNAL" | "PUBLIC") => void;
  visibility: "INTERNAL" | "PUBLIC";
}) {
  return (
    <form
      className="comment-composer"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor="ticket-comment">
        {analyst ? "Add an update" : "Add a public comment"}
      </label>
      <p id="comment-help">
        {visibility === "PUBLIC"
          ? "Visible to the employee and authorized analysts."
          : "Visible only to authorized analysts."}
      </p>
      {analyst && (
        <select
          aria-label="Comment visibility"
          onChange={(event) =>
            onVisibilityChange?.(event.target.value as "INTERNAL" | "PUBLIC")
          }
          value={visibility}
        >
          <option value="PUBLIC">Public comment</option>
          <option value="INTERNAL">Internal note</option>
        </select>
      )}
      <textarea
        aria-describedby="comment-help"
        id="ticket-comment"
        onChange={(event) => {
          onBodyChange(event.target.value);
        }}
        required
        rows={4}
        value={body}
      />
      <Button disabled={disabled} type="submit">
        {disabled
          ? "Posting…"
          : visibility === "INTERNAL"
            ? "Post internal note"
            : "Post public comment"}
      </Button>
    </form>
  );
}

export function TicketSidePanel({
  children,
  title = "Ticket information",
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <aside className="ticket-side-panel" aria-labelledby="side-panel-heading">
      <h2 id="side-panel-heading">{title}</h2>
      {children}
    </aside>
  );
}

export function ParticipantCard({
  name,
  role,
}: {
  name: string;
  role: string;
}) {
  return (
    <article className="participant-card">
      <Avatar name={name} />
      <div>
        <strong>{name}</strong>
        <small>{role}</small>
      </div>
    </article>
  );
}
