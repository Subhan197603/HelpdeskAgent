"""PostgreSQL validation for the Task 10.1 OAC reporting model."""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-reporting-test"
PORT = "55459"
DATABASE = "reporting_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
ANALYST_ID = UUID("22000000-0000-0000-0000-000000000004")
FORBIDDEN_COLUMN_PATTERNS = (
    "summary",
    "description",
    "comment",
    "email",
    "body",
    "user_name",
    "display_name",
    "reporter",
    "assignee_user_id",
    "actor_user_id",
)


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and result.returncode:
        pytest.fail(result.stdout + result.stderr)
    return result


def _psql_as(user: str, sql: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        user,
        "-d",
        DATABASE,
        "-Atqc",
        sql,
        check=check,
    )


def _psql(sql: str) -> str:
    return _psql_as("postgres", sql).stdout.strip()


def _migrate(*arguments: str) -> None:
    environment = _environment()
    environment["MIGRATION_DATABASE_URL"] = (
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
    )
    result = subprocess.run(
        ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", *arguments],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module", autouse=True)
def reporting_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            command = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                command += ["-v", "app_password=helpdesk"]
            _compose(*command, "-U", "postgres", "-d", DATABASE, "-f", file)
        _migrate("stamp")
        _migrate("upgrade")
        for file in ("/development/identity_personas.sql", "/development/catalogue.sql"):
            _compose(
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
                DATABASE,
                "-f",
                file,
            )
        _psql(
            """
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='reporting_login') THEN
                CREATE ROLE reporting_login LOGIN PASSWORD 'reporting'
                  IN ROLE helpdesk_reporting;
              END IF;
            END $$;
            """
        )
        _seed()
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _seed() -> None:
    _psql(
        f"""
        INSERT INTO itsm.ticket(
          ticket_id,tenant_id,project_id,request_type_id,request_type_version_id,
          work_type_id,workflow_version_id,status_id,summary,description,
          reporter_user_id,priority_code,channel_code,created_by,updated_by)
        SELECT fixture.ticket_id,'{TENANT_ID}',request_type.project_id,
          request_type.request_type_id,request_version.request_type_version_id,
          request_type.work_type_id,'32100000-0000-0000-0000-000000000001',
          fixture.status_id,fixture.summary,'Contact reporter@example.test',
          '{ANALYST_ID}','P3','PORTAL','{ANALYST_ID}','{ANALYST_ID}'
        FROM (VALUES
          ('84000000-0000-0000-0000-000000000001'::uuid,
            '32200000-0000-0000-0000-000000000002'::uuid,'Reporting seed one'),
          ('84000000-0000-0000-0000-000000000002'::uuid,
            '32200000-0000-0000-0000-000000000002'::uuid,'Reporting seed two')
        ) fixture(ticket_id,status_id,summary)
        JOIN config.request_type request_type
          ON request_type.request_type_id='33000000-0000-0000-0000-000000000001'
        JOIN config.request_type_version request_version
          ON request_version.request_type_id=request_type.request_type_id
         AND request_version.version_status='PUBLISHED'
        ON CONFLICT (ticket_id) DO NOTHING;

        INSERT INTO itsm.ticket_sla(
          tenant_id,ticket_id,sla_definition_id,sla_goal_id,sla_goal_version_id,
          business_calendar_version_id,state_code,started_at,target_at)
        SELECT '{TENANT_ID}','84000000-0000-0000-0000-000000000001',
          goal.sla_definition_id,goal.sla_goal_id,
          goal_version.sla_goal_version_id,
          goal_version.business_calendar_version_id,'RUNNING',now(),
          now() + interval '4 hours'
        FROM config.sla_goal_version goal_version
        JOIN config.sla_goal goal ON goal.sla_goal_id=goal_version.sla_goal_id
        ORDER BY goal_version.sla_goal_version_id
        LIMIT 1
        ON CONFLICT DO NOTHING;

        INSERT INTO ai.usage_ledger(
          tenant_id,provider_alias,model_alias,use_case_code,input_tokens,
          output_tokens,estimated_cost,currency_code)
        VALUES ('{TENANT_ID}','fake','analyst-model','TICKET_ANALYSIS',100,50,
          0.01,'USD');

        INSERT INTO ai.feedback(tenant_id,feedback_type,decision_code,reason_code)
        VALUES ('{TENANT_ID}','ANALYST_ACCEPTANCE','REJECTED','INCORRECT');
        """
    )


@pytest.mark.integration
def test_reporting_role_reads_views_only_and_operational_access_is_revoked() -> None:
    assert _psql_as("reporting_login", "SELECT count(*) FROM reporting.fact_ticket").stdout.strip()
    denied_table = _psql_as("reporting_login", "SELECT count(*) FROM itsm.ticket", check=False)
    assert denied_table.returncode != 0
    assert "permission denied" in denied_table.stderr
    denied_identity = _psql_as(
        "reporting_login", "SELECT count(*) FROM identity.app_user", check=False
    )
    assert denied_identity.returncode != 0
    denied_ai = _psql_as("reporting_login", "SELECT count(*) FROM ai.feedback", check=False)
    assert denied_ai.returncode != 0
    denied_write = _psql_as("reporting_login", "DELETE FROM reporting.fact_ticket", check=False)
    assert denied_write.returncode != 0


@pytest.mark.integration
def test_reporting_facts_reconcile_with_source_transactions() -> None:
    assert _psql("SELECT count(*) FROM reporting.fact_ticket") == _psql(
        "SELECT count(*) FROM itsm.ticket"
    )
    assert _psql("SELECT count(*) FROM reporting.fact_ticket_sla") == _psql(
        "SELECT count(*) FROM itsm.ticket_sla"
    )
    assert _psql("SELECT count(*) FROM reporting.fact_approval") == _psql(
        "SELECT count(*) FROM itsm.ticket_approval"
    )
    assert _psql("SELECT count(*) FROM reporting.fact_ai_usage") == _psql(
        "SELECT count(*) FROM ai.usage_ledger"
    )
    assert _psql("SELECT count(*) FROM reporting.fact_ai_feedback") == _psql(
        "SELECT count(*) FROM ai.feedback"
    )
    assert _psql("SELECT coalesce(sum(input_tokens),0) FROM reporting.fact_ai_usage") == _psql(
        "SELECT coalesce(sum(input_tokens),0) FROM ai.usage_ledger"
    )
    assert (
        _psql(
            "SELECT count(*) FROM reporting.fact_ai_feedback "
            "WHERE decision_code='REJECTED' AND reason_code='INCORRECT'"
        )
        == "1"
    )


@pytest.mark.integration
def test_reporting_views_are_tenant_scoped_utc_and_free_of_pii() -> None:
    facts = _psql(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='reporting' AND table_name LIKE 'fact%'"
    ).splitlines()
    assert len(facts) >= 5
    for fact in facts:
        assert (
            _psql(
                "SELECT count(*) FROM information_schema.columns "
                f"WHERE table_schema='reporting' AND table_name='{fact}' "
                "AND column_name='tenant_id'"
            )
            == "1"
        )
    for pattern in FORBIDDEN_COLUMN_PATTERNS:
        offenders = _psql(
            "SELECT table_name || '.' || column_name FROM information_schema.columns "
            f"WHERE table_schema='reporting' AND column_name LIKE '%{pattern}%'"
        )
        assert offenders == "", f"PII-risk column exposed: {offenders}"
    non_utc = _psql(
        "SELECT table_name || '.' || column_name FROM information_schema.columns "
        "WHERE table_schema='reporting' AND (column_name LIKE '%_at' "
        "OR column_name='extraction_watermark') "
        "AND data_type <> 'timestamp with time zone'"
    )
    assert non_utc == "", f"Non-timestamptz temporal column: {non_utc}"


@pytest.mark.integration
def test_ticket_event_feed_supports_incremental_extraction() -> None:
    total = int(_psql("SELECT count(*) FROM reporting.feed_ticket_events"))
    assert total >= 2
    watermark = _psql(
        "SELECT max(event_id) FROM ("
        "SELECT event_id FROM reporting.feed_ticket_events ORDER BY event_id LIMIT 1"
        ") first_event"
    )
    newer = int(
        _psql(f"SELECT count(*) FROM reporting.feed_ticket_events WHERE event_id > {watermark}")
    )
    assert newer == total - 1
    assert (
        _psql(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='itsm' "
            "AND indexname='ticket_event_tenant_feed_ix'"
        )
        == "1"
    )
