"""Runtime-role PostgreSQL validation for read-only AI governance."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.ai.governance_repository import AIGovernanceRepository
from apps.api.app.core.context import RequestContext
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-ai-governance-test"
PORT = "55557"
DATABASE = "ai_governance_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("20000000-0000-0000-0000-000000000099")
USER_ID = UUID("22000000-0000-0000-0000-000000000001")
POLICY_ID = UUID("91000000-0000-0000-0000-000000000010")
OTHER_POLICY_ID = UUID("91000000-0000-0000-0000-000000000099")


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


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


def _psql(sql: str) -> str:
    result = _compose(
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
        "-Atqc",
        sql,
    )
    return result.stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def ai_governance_database() -> Iterator[None]:
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
            "/development/identity_personas.sql",
        )
        _seed()
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _seed() -> None:
    _psql(
        f"""
        INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
        VALUES ('{OTHER_TENANT_ID}','AI_OTHER','Other AI Tenant');

        INSERT INTO ai.prompt_template(prompt_template_id,tenant_id,prompt_code,prompt_name)
        VALUES ('91000000-0000-0000-0000-000000000001','{TENANT_ID}','EMPLOYEE','Employee');
        INSERT INTO ai.prompt_version(prompt_version_id,prompt_template_id,version_number,
          version_status,prompt_text,published_at)
        VALUES ('91000000-0000-0000-0000-000000000002',
          '91000000-0000-0000-0000-000000000001',1,'PUBLISHED','secret prompt',now());
        INSERT INTO ai.tool_set(tool_set_id,tenant_id,tool_set_code,tool_set_name)
        VALUES ('91000000-0000-0000-0000-000000000003','{TENANT_ID}','NONE','No tools');
        INSERT INTO ai.tool_set_version(tool_set_version_id,tool_set_id,version_number,
          version_status,tool_definitions_json,published_at)
        VALUES ('91000000-0000-0000-0000-000000000004',
          '91000000-0000-0000-0000-000000000003',1,'PUBLISHED','[]',now());
        INSERT INTO ai.retrieval_configuration(retrieval_configuration_id,tenant_id,
          retrieval_code,retrieval_name)
        VALUES ('91000000-0000-0000-0000-000000000005','{TENANT_ID}',
          'HYBRID_EVIDENCE','Hybrid evidence');
        INSERT INTO ai.retrieval_configuration_version(
          retrieval_configuration_version_id,retrieval_configuration_id,version_number,
          version_status,configuration_json,published_at)
        VALUES ('91000000-0000-0000-0000-000000000006',
          '91000000-0000-0000-0000-000000000005',1,'PUBLISHED',
          '{{"semantic_weight":0.5,"lexical_weight":0.5}}',now());
        INSERT INTO ai.model_policy(model_policy_id,tenant_id,policy_code,policy_name)
        VALUES ('91000000-0000-0000-0000-000000000007','{TENANT_ID}',
          'EMPLOYEE_MODEL','Employee model');
        INSERT INTO ai.model_policy_version(model_policy_version_id,model_policy_id,
          version_number,version_status,provider_alias,model_alias,published_at)
        VALUES ('91000000-0000-0000-0000-000000000008',
          '91000000-0000-0000-0000-000000000007',1,'PUBLISHED',
          'openai','employee-safe',now());
        INSERT INTO ai.agent_configuration(agent_configuration_id,tenant_id,agent_code,agent_name)
        VALUES ('91000000-0000-0000-0000-000000000009','{TENANT_ID}',
          'EMPLOYEE_HELPDESK','Employee helpdesk');
        INSERT INTO ai.agent_configuration_version(agent_configuration_version_id,
          agent_configuration_id,version_number,version_status,prompt_version_id,
          tool_set_version_id,retrieval_configuration_version_id,model_policy_version_id,
          published_at)
        VALUES ('91000000-0000-0000-0000-00000000000a',
          '91000000-0000-0000-0000-000000000009',1,'PUBLISHED',
          '91000000-0000-0000-0000-000000000002',
          '91000000-0000-0000-0000-000000000004',
          '91000000-0000-0000-0000-000000000006',
          '91000000-0000-0000-0000-000000000008',now());
        INSERT INTO ai.feature_policy(feature_policy_id,tenant_id,scope_type,enabled_flag,
          daily_budget,monthly_budget,budget_currency,warning_threshold_percent,
          hard_stop_threshold_percent,approval_status)
        VALUES ('{POLICY_ID}','{TENANT_ID}','TENANT',true,10,100,'USD',80,100,'APPROVED'),
          ('{OTHER_POLICY_ID}','{OTHER_TENANT_ID}','TENANT',true,999,9999,'USD',80,100,'APPROVED');
        INSERT INTO ai.usage_ledger(tenant_id,agent_configuration_id,user_id,provider_alias,
          model_alias,use_case_code,input_tokens,output_tokens,cached_tokens,tool_call_count,
          estimated_cost,currency_code,occurred_at)
        VALUES ('{TENANT_ID}','91000000-0000-0000-0000-000000000009','{USER_ID}',
          'openai','employee-safe','PROVIDER_CALL',100,50,5,0,8.5,'USD',now()),
          ('{OTHER_TENANT_ID}',NULL,NULL,'anthropic','foreign-model','PROVIDER_CALL',
          999,999,0,0,999,'USD',now());
        """
    )


def _context() -> RequestContext:
    return RequestContext(
        TENANT_ID,
        USER_ID,
        "ai-admin",
        frozenset({"AI_ADMIN"}),
        frozenset(),
        None,
        "91000000-0000-0000-0000-0000000000ff",
        "ai-governance-integration",
    )


def _engine() -> AsyncEngine:
    return create_async_engine(
        f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
    )


def _business_statements(statements: list[str], prefix: str) -> list[str]:
    return [item for item in statements if item.lstrip().upper().startswith(prefix)]


@pytest.mark.integration
def test_runtime_reads_are_tenant_scoped_bounded_and_secret_free() -> None:
    async def exercise() -> None:
        engine = _engine()
        statements: list[str] = []
        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            lambda _connection, _cursor, statement, _parameters, _context, _many: statements.append(
                statement
            ),
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with SqlAlchemyUnitOfWork(sessions, _context(), rls_enabled=True) as uow:
                repository = AIGovernanceRepository(uow.session)
                statements.clear()
                assignments = await repository.assignments(TENANT_ID)
                assert len(_business_statements(statements, "SELECT")) == 1
                assert [item.agent_code for item in assignments] == ["EMPLOYEE_HELPDESK"]
                assert all("secret prompt" not in str(item) for item in assignments)

                statements.clear()
                retrieval = await repository.retrieval(TENANT_ID)
                assert len(_business_statements(statements, "SELECT")) == 1
                assert retrieval is not None and retrieval.tenant_specific

                statements.clear()
                policies = await repository.policies(TENANT_ID, limit=51, offset=0)
                assert len(_business_statements(statements, "WITH")) == 1
                assert POLICY_ID in {item.feature_policy_id for item in policies}
                assert OTHER_POLICY_ID not in {item.feature_policy_id for item in policies}

                statements.clear()
                usage = await repository.usage(
                    TENANT_ID, datetime.now(UTC) - timedelta(days=1), datetime.now(UTC)
                )
                assert len(_business_statements(statements, "WITH")) == 1
                assert usage.totals_by_currency[0]["requests"] == 1
                assert usage.providers[0]["model_alias"] == "employee-safe"
                assert "foreign-model" not in str(usage)
                await uow.commit()
        finally:
            await engine.dispose()

    asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.integration
def test_runtime_role_cannot_mutate_or_delete_ai_policies() -> None:
    async def exercise() -> None:
        engine = _engine()
        try:
            async with engine.begin() as connection:
                with pytest.raises(ProgrammingError):
                    await connection.execute(
                        text(
                            "UPDATE ai.feature_policy SET enabled_flag=false "
                            "WHERE feature_policy_id=:policy_id"
                        ),
                        {"policy_id": POLICY_ID},
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.integration
def test_rls_preserves_tenant_usage_and_policy_isolation() -> None:
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
        "/baseline/09_optional_rls.sql",
    )

    async def exercise() -> None:
        engine = _engine()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with SqlAlchemyUnitOfWork(sessions, _context(), rls_enabled=True) as uow:
                policies = await AIGovernanceRepository(uow.session).policies(
                    TENANT_ID, limit=100, offset=0
                )
                usage = await AIGovernanceRepository(uow.session).usage(
                    TENANT_ID, datetime.now(UTC) - timedelta(days=1), datetime.now(UTC)
                )
                assert OTHER_POLICY_ID not in {item.feature_policy_id for item in policies}
                assert usage.totals_by_currency[0]["estimated_cost"] == 8.5
                await uow.commit()
        finally:
            await engine.dispose()

    asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop)
