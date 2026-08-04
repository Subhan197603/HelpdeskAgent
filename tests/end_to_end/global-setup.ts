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

  // Bind the stub identity provider's subject to the development agent so the
  // OIDC sign-in end-to-end test authenticates against real validation.
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
    "-c",
    `INSERT INTO identity.oidc_tenant_mapping(
       oidc_tenant_mapping_id, tenant_id, provider_code, trusted_issuer,
       organization_claim_value
     ) VALUES (
       '24000000-0000-0000-0000-0000000000e1',
       '20000000-0000-0000-0000-000000000001',
       'TEST_OIDC', 'http://127.0.0.1:59180', NULL
     ) ON CONFLICT DO NOTHING;
     INSERT INTO identity.external_identity(
       external_identity_id, tenant_id, oidc_tenant_mapping_id,
       user_id, external_subject
     ) VALUES (
       '25000000-0000-0000-0000-0000000000e1',
       '20000000-0000-0000-0000-000000000001',
       '24000000-0000-0000-0000-0000000000e1',
       '22000000-0000-0000-0000-000000000004', 'oidc-agent'
     ) ON CONFLICT DO NOTHING;`,
  );
}
