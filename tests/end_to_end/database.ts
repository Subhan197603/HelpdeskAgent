import { execFileSync } from "node:child_process";

export const composeProject = "fusion-helpdesk-task-3-3-e2e";

function environment(): NodeJS.ProcessEnv {
  return { ...process.env, POSTGRES_HOST_PORT: "55549" };
}

export function dockerCompose(...args: string[]): void {
  execFileSync(
    "docker",
    ["compose", "--project-name", composeProject, ...args],
    { env: environment(), stdio: "inherit" },
  );
}

export function run(command: string, args: string[]): void {
  execFileSync(command, args, { env: environment(), stdio: "inherit" });
}
