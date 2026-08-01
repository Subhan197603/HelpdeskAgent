import type { ReactNode } from "react";

import { ApiProblem } from "../lib/api";

export function StatusPanel({ children }: { children: ReactNode }) {
  return (
    <div className="status-panel" role="status">
      {children}
    </div>
  );
}

export function ErrorSummary({ error }: { error: unknown }) {
  const problem =
    error instanceof ApiProblem
      ? error
      : new ApiProblem(500, "Something went wrong. Try again.");
  const heading =
    problem.status === 401 || problem.status === 403
      ? "You are not authorized"
      : problem.status === 409
        ? "Your information is out of date"
        : "We could not complete that request";
  return (
    <section
      className="error-summary"
      role="alert"
      aria-labelledby="error-heading"
      tabIndex={-1}
    >
      <h2 id="error-heading">{heading}</h2>
      <p>{problem.message}</p>
      {problem.fieldErrors.length > 0 && (
        <ul>
          {problem.fieldErrors.map((item) => (
            <li key={`${item.field}-${item.message}`}>
              <strong>{item.field}:</strong> {item.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
