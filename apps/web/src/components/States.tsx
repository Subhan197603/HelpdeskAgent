import type { ReactNode } from "react";

import { ApiProblem } from "../lib/api";

interface StateProps {
  action?: ReactNode;
  description: string;
  role?: "alert" | "status";
  title: string;
}

function StatePanel({ action, description, role, title }: StateProps) {
  return (
    <section
      className="state-panel"
      aria-labelledby={`state-${title.replaceAll(" ", "-").toLowerCase()}`}
      role={role}
    >
      <span aria-hidden="true" className="state-panel__icon">
        i
      </span>
      <div>
        <h2 id={`state-${title.replaceAll(" ", "-").toLowerCase()}`}>
          {title}
        </h2>
        <p>{description}</p>
        {action}
      </div>
    </section>
  );
}

export function EmptyState(props: Partial<StateProps>) {
  return (
    <StatePanel
      description={props.description ?? "There is nothing to show yet."}
      title={props.title ?? "No results"}
      action={props.action}
    />
  );
}

export function UnauthorizedState(props: Partial<StateProps>) {
  return (
    <StatePanel
      description={
        props.description ??
        "Your current permissions do not allow access to this area."
      }
      title={props.title ?? "You are not authorized"}
      action={props.action}
    />
  );
}

export function ConflictState(props: Partial<StateProps>) {
  return (
    <StatePanel
      description={
        props.description ??
        "Reload the latest information before trying again."
      }
      title={props.title ?? "Your information is out of date"}
      action={props.action}
      role="alert"
    />
  );
}

export function ErrorState(props: Partial<StateProps>) {
  return (
    <StatePanel
      description={
        props.description ??
        "Try again, or contact support if the problem continues."
      }
      title={props.title ?? "Something went wrong"}
      action={props.action}
    />
  );
}

export function LoadingSkeleton({
  label = "Loading content",
  lines = 3,
}: {
  label?: string;
  lines?: number;
}) {
  return (
    <div
      aria-busy="true"
      aria-label={label}
      className="loading-skeleton"
      role="status"
    >
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

export function ErrorSummary({ error }: { error: unknown }) {
  const problem =
    error instanceof ApiProblem
      ? error
      : new ApiProblem(500, "Something went wrong. Try again.");
  if (problem.status === 401 || problem.status === 403)
    return <UnauthorizedState description={problem.message} />;
  if (problem.status === 409)
    return <ConflictState description={problem.message} />;
  return (
    <section
      className="error-summary"
      role="alert"
      aria-labelledby="error-heading"
      tabIndex={-1}
    >
      <h2 id="error-heading">We could not complete that request</h2>
      <p>{problem.message}</p>
      {problem.fieldErrors.length > 0 && (
        <ul>
          {problem.fieldErrors.map((item) => (
            <li key={`${item.field}-${item.message}`}>
              <a href={`#field-${item.field}`}>
                <strong>{item.field}:</strong> {item.message}
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function StatusPanel({ children }: { children: ReactNode }) {
  return (
    <div className="status-panel" role="status">
      {children}
    </div>
  );
}
