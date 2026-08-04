import createClient from "openapi-fetch";

import type { paths } from "./generated";

export type { components, paths } from "./generated";

export type HelpdeskAuth =
  | { mode: "developer"; identity: string }
  | { mode: "bearer"; getToken: () => string | null };

export interface HelpdeskClientOptions {
  baseUrl: string;
  /** Developer-identity shorthand kept for existing call sites. */
  identity?: string;
  auth?: HelpdeskAuth;
}

export function createHelpdeskClient({
  baseUrl,
  identity,
  auth,
}: HelpdeskClientOptions) {
  const resolved: HelpdeskAuth = auth ?? {
    mode: "developer",
    identity: identity ?? "",
  };
  const client = createClient<paths>({
    baseUrl,
    headers:
      resolved.mode === "developer"
        ? { "X-Developer-User": resolved.identity }
        : undefined,
  });
  if (resolved.mode === "bearer") {
    client.use({
      onRequest({ request }) {
        const token = resolved.getToken();
        if (token) request.headers.set("Authorization", `Bearer ${token}`);
        return request;
      },
    });
  }
  return client;
}

export type HelpdeskClient = ReturnType<typeof createHelpdeskClient>;
