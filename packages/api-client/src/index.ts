import createClient from "openapi-fetch";

import type { paths } from "./generated";

export type { components, paths } from "./generated";

export interface HelpdeskClientOptions {
  baseUrl: string;
  identity: string;
}

export function createHelpdeskClient({
  baseUrl,
  identity,
}: HelpdeskClientOptions) {
  return createClient<paths>({
    baseUrl,
    headers: { "X-Developer-User": identity },
  });
}

export type HelpdeskClient = ReturnType<typeof createHelpdeskClient>;
