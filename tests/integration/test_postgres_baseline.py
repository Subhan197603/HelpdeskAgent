import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PROJECT = "fusion-helpdesk-baseline-test"
DATABASE_NAME = "helpdesk"
EXPECTED_SCHEMAS = {"identity", "config", "itsm", "kb", "ai", "audit", "integration"}
EXPECTED_EXTENSIONS = {"pgcrypto", "pg_trgm", "unaccent", "vector"}


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = environment.get("BASELINE_TEST_POSTGRES_HOST_PORT", "55439")
    return environment


def _run_compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", "compose", "--project-name", COMPOSE_PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if check and completed.returncode != 0:
        pytest.fail(
            f"Docker Compose command failed ({completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _run_psql(sql: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run_compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        DATABASE_NAME,
        "-Atqc",
        sql,
        check=check,
    )


def _query_values(sql: str) -> set[str]:
    output = _run_psql(sql).stdout
    return {line for line in output.splitlines() if line}


@pytest.fixture(scope="module", autouse=True)
def installed_clean_baseline() -> Iterator[None]:
    _run_compose("up", "-d", "--wait", "postgres")
    try:
        installation = _run_compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            DATABASE_NAME,
            "-f",
            "/baseline/install_all.sql",
        )
        assert "Base installation completed." in installation.stdout
        yield
    finally:
        _run_compose("down", "--volumes", "--remove-orphans", check=False)


@pytest.mark.integration
def test_expected_schemas_and_extensions_exist() -> None:
    schemas = _query_values(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name = ANY "
        "(ARRAY['identity','config','itsm','kb','ai','audit','integration']);"
    )
    extensions = _query_values(
        "SELECT extname FROM pg_extension "
        "WHERE extname = ANY (ARRAY['pgcrypto','pg_trgm','unaccent','vector']);"
    )

    assert schemas == EXPECTED_SCHEMAS
    assert extensions == EXPECTED_EXTENSIONS


@pytest.mark.integration
def test_representative_tables_exist_in_every_schema() -> None:
    expected_tables = {
        "identity.tenant",
        "config.request_type_version",
        "config.application_environment",
        "itsm.ticket",
        "kb.document",
        "ai.feature_policy",
        "audit.audit_event",
        "integration.idempotency_record",
    }
    tables = _query_values(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_schema = ANY "
        "(ARRAY['identity','config','itsm','kb','ai','audit','integration']);"
    )

    assert tables >= expected_tables


@pytest.mark.integration
def test_key_constraints_and_indexes_exist() -> None:
    expected_constraints = {
        "idempotency_record_tenant_id_operation_code_idempotency_key_key",
        "product_release_family_match_ck",
        "priority_matrix_dates_ck",
        "attachment_release_ck",
        "ai_feature_policy_scope_ck",
        "service_ownership_principal_ck",
    }
    constraints = _query_values(
        "SELECT conname FROM pg_constraint WHERE conname = ANY (ARRAY["
        "'idempotency_record_tenant_id_operation_code_idempotency_key_key',"
        "'product_release_family_match_ck','priority_matrix_dates_ck',"
        "'attachment_release_ck','ai_feature_policy_scope_ck',"
        "'service_ownership_principal_ck']);"
    )
    indexes = _query_values(
        "SELECT indexname FROM pg_indexes WHERE indexname = ANY (ARRAY["
        "'idempotency_lease_ix','environment_one_current_release_ux',"
        "'audit_event_resource_time_ix','ai_usage_ledger_budget_ix']);"
    )

    assert constraints == expected_constraints
    assert indexes == {
        "idempotency_lease_ix",
        "environment_one_current_release_ux",
        "audit_event_resource_time_ix",
        "ai_usage_ledger_budget_ix",
    }


@pytest.mark.integration
def test_foundational_reference_data_and_release_families_are_distinct() -> None:
    assert _query_values("SELECT count(*) FROM config.priority_matrix;") == {"16"}
    assert _query_values(
        "SELECT release_family || '/' || release_code FROM config.product_release ORDER BY 1;"
    ) == {
        "FUSION_APPLICATIONS/26C",
        "FUSION_DATA_INTELLIGENCE/26.R2",
    }
    assert _query_values(
        "SELECT release_family || '/' || release_code FROM kb.release ORDER BY 1;"
    ) == {
        "FUSION_APPLICATIONS/26C",
        "FUSION_DATA_INTELLIGENCE/26.R2",
    }


@pytest.mark.integration
def test_foundational_governance_controls_exist_without_credentials() -> None:
    version_tables = _query_values(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_name IN ('request_type_version','routing_rule_version',"
        "'sla_definition_version','approval_definition_version',"
        "'notification_template_version','prompt_version','tool_set_version',"
        "'retrieval_configuration_version','agent_configuration_version',"
        "'embedding_configuration_version');"
    )
    credential_columns = _query_values(
        "SELECT table_name || '.' || column_name FROM information_schema.columns "
        "WHERE table_schema = 'ai' AND column_name ~* '(api_key|password|credential|secret)';"
    )

    assert len(version_tables) == 10
    assert credential_columns == set()
    assert _query_values(
        "SELECT enabled_flag::text FROM ai.feature_policy WHERE scope_type = 'GLOBAL';"
    ) == {"false"}


@pytest.mark.integration
def test_email_retention_attachment_audit_and_service_foundations_exist() -> None:
    required_columns = _query_values(
        "SELECT table_schema || '.' || table_name || '.' || column_name "
        "FROM information_schema.columns WHERE "
        "(table_schema, table_name, column_name) IN ("
        "('integration','email_message','original_message_object_uri'),"
        "('itsm','ticket_attachment','quarantine_object_uri'),"
        "('itsm','ticket_attachment','protected_object_uri'),"
        "('itsm','ticket_attachment','scanner_version'),"
        "('config','service_node','criticality_code'),"
        "('audit','audit_event','correlation_id'));"
    )

    assert len(required_columns) == 6
    assert _query_values(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'integration' AND table_name = 'email_message' "
        "AND column_name IN ('raw_mime','mime_body','attachment_bytes');"
    ) == {"0"}


@pytest.mark.integration
def test_demo_data_is_not_part_of_normal_installation() -> None:
    assert _query_values("SELECT count(*) FROM identity.tenant WHERE tenant_code = 'DEMO';") == {
        "0"
    }
    assert _query_values("SELECT count(*) FROM itsm.ticket;") == {"0"}


@pytest.mark.integration
def test_immutable_history_is_not_mutable_by_runtime_roles() -> None:
    privileges = _query_values(
        "SELECT role_name || ':' || table_name || ':' || privilege_type FROM ("
        "VALUES ('helpdesk_app'), ('helpdesk_worker')) roles(role_name) "
        "CROSS JOIN (VALUES ('ticket_event'), ('audit_event'), "
        "('retrieval_evidence')) tables(table_name) "
        "CROSS JOIN (VALUES ('UPDATE'), ('DELETE')) privileges(privilege_type) "
        "WHERE has_table_privilege(role_name, CASE table_name "
        "WHEN 'ticket_event' THEN 'itsm.ticket_event' "
        "WHEN 'audit_event' THEN 'audit.audit_event' "
        "ELSE 'ai.retrieval_evidence' END, privilege_type);"
    )

    assert privileges == set()

    _run_psql(
        "INSERT INTO audit.audit_event "
        "(actor_type, action_code, resource_type, outcome_code) "
        "VALUES ('SYSTEM', 'BASELINE_TEST', 'DATABASE', 'SUCCESS');"
    )
    attempted_update = _run_psql(
        "UPDATE audit.audit_event SET action_code = 'MUTATED' WHERE action_code = 'BASELINE_TEST';",
        check=False,
    )
    assert attempted_update.returncode != 0


@pytest.mark.integration
def test_schema_ownership_and_runtime_roles_are_least_privilege() -> None:
    owners = _query_values(
        "SELECT n.nspname || ':' || pg_get_userbyid(n.nspowner) FROM pg_namespace n "
        "WHERE n.nspname = ANY "
        "(ARRAY['identity','config','itsm','kb','ai','audit','integration']);"
    )
    elevated_runtime_roles = _query_values(
        "SELECT rolname FROM pg_roles WHERE rolname IN "
        "('helpdesk_app','helpdesk_worker','helpdesk_reporting','helpdesk_readonly') "
        "AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolcanlogin);"
    )

    assert owners == {f"{schema}:helpdesk_owner" for schema in EXPECTED_SCHEMAS}
    assert elevated_runtime_roles == set()


@pytest.mark.integration
def test_database_is_healthy_after_installation() -> None:
    assert _query_values("SELECT 1;") == {"1"}
    health = _run_compose("ps", "postgres", "--format", "{{.Health}}")
    assert health.stdout.strip() == "healthy"


@pytest.mark.integration
def test_optional_demo_installers_are_separate_and_valid() -> None:
    for script_name in ("10_demo_bootstrap.sql", "11_demo_ticket.sql"):
        _run_compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            DATABASE_NAME,
            "-f",
            f"/baseline/{script_name}",
        )

    assert _query_values("SELECT tenant_code FROM identity.tenant;") == {"DEMO"}
    assert _query_values("SELECT ticket_key FROM itsm.ticket;") == {"IT-1"}


@pytest.mark.integration
def test_optional_rls_script_covers_foundational_tenant_tables() -> None:
    _run_compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        DATABASE_NAME,
        "-f",
        "/baseline/09_optional_rls.sql",
    )

    rls_tables = _query_values(
        "SELECT n.nspname || '.' || c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relrowsecurity AND (n.nspname, c.relname) IN ("
        "('integration','idempotency_record'),('integration','email_message'),"
        "('ai','feature_policy'),('audit','audit_event'),"
        "('config','application_environment'),('itsm','ticket_communication'));"
    )

    assert len(rls_tables) == 6


@pytest.mark.integration
def test_uninstall_script_refuses_without_local_confirmation() -> None:
    unconfirmed = _run_compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        DATABASE_NAME,
        "-f",
        "/baseline/uninstall_all.sql",
        check=False,
    )

    assert "Refusing uninstall" in unconfirmed.stdout
    assert _query_values("SELECT to_regclass('itsm.ticket') IS NOT NULL;") == {"t"}


@pytest.mark.integration
def test_repeated_baseline_installation_fails_nonzero() -> None:
    repeated_install = _run_compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        DATABASE_NAME,
        "-f",
        "/baseline/install_all.sql",
        check=False,
    )

    assert repeated_install.returncode != 0
