import { dockerCompose, run } from "./database";

export default function globalSetup(): void {
  dockerCompose("up", "-d", "--wait", "postgres");
  dockerCompose(
    "exec",
    "-T",
    "postgres",
    "psql",
    "-v",
    "ON_ERROR_STOP=1",
    "-U",
    "postgres",
    "-d",
    "helpdesk",
    "-f",
    "/baseline/install_all.sql",
  );
  dockerCompose(
    "exec",
    "-T",
    "postgres",
    "psql",
    "-v",
    "ON_ERROR_STOP=1",
    "-v",
    "app_password=helpdesk",
    "-U",
    "postgres",
    "-d",
    "helpdesk",
    "-f",
    "/runtime-config/configure_local_runtime.sql",
  );

  const migrationEnvironment =
    "postgresql+psycopg://postgres:postgres@127.0.0.1:55449/helpdesk";
  process.env.MIGRATION_DATABASE_URL = migrationEnvironment;
  run("uv", ["run", "python", "-m", "apps.api.app.db.migrations_cli", "stamp"]);
  run("uv", [
    "run",
    "python",
    "-m",
    "apps.api.app.db.migrations_cli",
    "upgrade",
    "head",
  ]);

  for (const fixture of ["identity_personas.sql", "catalogue.sql"]) {
    dockerCompose(
      "exec",
      "-T",
      "postgres",
      "psql",
      "-v",
      "ON_ERROR_STOP=1",
      "-U",
      "postgres",
      "-d",
      "helpdesk",
      "-f",
      `/development/${fixture}`,
    );
  }
}
