import { createHelpdeskClient } from "@fusion-helpdesk/api-client";

export const apiBaseUrl =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export class ApiProblem extends Error {
  constructor(
    readonly status: number,
    detail: string,
    readonly fieldErrors: readonly {
      field: string;
      message: string;
    }[] = [],
  ) {
    super(detail);
  }
}

export function apiClient(identity: string) {
  return createHelpdeskClient({ baseUrl: apiBaseUrl, identity });
}

export function unwrap<T>(result: {
  data?: T;
  error?: unknown;
  response: Response;
}): T {
  if (result.data !== undefined) return result.data;
  const problem = result.error as
    | {
        detail?: string;
        errors?:
          Record<string, string[]> | { field?: string; message?: string }[];
      }
    | undefined;
  const errors = Array.isArray(problem?.errors)
    ? problem.errors.map((item) => ({
        field: item.field ?? "request",
        message: item.message ?? "Invalid value.",
      }))
    : Object.entries(problem?.errors ?? {}).flatMap(([field, messages]) =>
        messages.map((message) => ({ field, message })),
      );
  throw new ApiProblem(
    result.response.status,
    problem?.detail ?? "The helpdesk could not complete this request.",
    errors,
  );
}

export function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
