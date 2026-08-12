"""PostgreSQL validation for Task 8.1 AI policy and immutable runtime evidence."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.ai.models import LLMResult, ModelUsage, ProviderRequest, ToolRequest
from apps.api.app.ai.repository import AIRepository, ToolAuditRecord
from apps.api.app.ai.resilience import CircuitBreaker, ResilientProviderExecutor
from apps.api.app.ai.service import AIDisabledError, AIGateway
from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import (
    AuthorizationResource,
    AuthorizationService,
    Permission,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-ai-runtime-test"
PORT = "55457"
DATABASE = "ai_runtime"
TENANT_ID = "20000000-0000-0000-0000-000000000001"
USER_ID = "22000000-0000-0000-0000-000000000005"
CONVERSATION_ID = "81000000-0000-0000-0000-000000000011"
OTHER_TENANT_ID = "20000000-0000-0000-0000-000000000099"


def _environment() -> dict[str, str]:
    result = os.environ.copy()
    result["POSTGRES_HOST_PORT"] = PORT
    return result


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


def _psql(sql: str) -> str:
    return _compose(
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
    ).stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def ai_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            arguments = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                arguments += ["-v", "app_password=helpdesk"]
            _compose(*arguments, "-U", "postgres", "-d", DATABASE, "-f", file)
        migration_environment = _environment()
        migration_environment["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
        )
        for command in ("stamp", "upgrade"):
            result = subprocess.run(
                ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", command],
                cwd=ROOT,
                env=migration_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
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
        _seed_policy()
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _seed_policy() -> None:
    _psql(
        f"""
        INSERT INTO ai.prompt_template(prompt_template_id,tenant_id,prompt_code,prompt_name)
        VALUES ('81000000-0000-0000-0000-000000000001','{TENANT_ID}','EMPLOYEE','Employee');
        INSERT INTO ai.prompt_version(prompt_version_id,prompt_template_id,version_number,
          version_status,prompt_text,published_at)
        VALUES ('81000000-0000-0000-0000-000000000002',
          '81000000-0000-0000-0000-000000000001',1,'PUBLISHED','Approved',now());
        INSERT INTO ai.tool_set(tool_set_id,tenant_id,tool_set_code,tool_set_name)
        VALUES ('81000000-0000-0000-0000-000000000003','{TENANT_ID}','EMPLOYEE','Employee');
        INSERT INTO ai.tool_set_version(tool_set_version_id,tool_set_id,version_number,
          version_status,tool_definitions_json,published_at)
        VALUES ('81000000-0000-0000-0000-000000000004',
          '81000000-0000-0000-0000-000000000003',1,'PUBLISHED','[]',now());
        INSERT INTO ai.retrieval_configuration(retrieval_configuration_id,tenant_id,
          retrieval_code,retrieval_name)
        VALUES ('81000000-0000-0000-0000-000000000005','{TENANT_ID}','EMPLOYEE','Employee');
        INSERT INTO ai.retrieval_configuration_version(retrieval_configuration_version_id,
          retrieval_configuration_id,version_number,version_status,configuration_json,published_at)
        VALUES ('81000000-0000-0000-0000-000000000006',
          '81000000-0000-0000-0000-000000000005',1,'PUBLISHED','{{}}',now());
        INSERT INTO ai.model_policy(model_policy_id,tenant_id,policy_code,policy_name)
        VALUES ('81000000-0000-0000-0000-000000000007','{TENANT_ID}','EMPLOYEE','Employee');
        INSERT INTO ai.model_policy_version(model_policy_version_id,model_policy_id,version_number,
          version_status,provider_alias,model_alias,fallback_provider_alias,
          fallback_model_alias,published_at)
        VALUES ('81000000-0000-0000-0000-000000000008',
          '81000000-0000-0000-0000-000000000007',1,'PUBLISHED','fake','fake-model',
          'fake','fallback-model',now());
        INSERT INTO ai.agent_configuration(agent_configuration_id,tenant_id,agent_code,agent_name)
        VALUES ('81000000-0000-0000-0000-000000000009','{TENANT_ID}',
          'EMPLOYEE_HELPDESK','Employee');
        INSERT INTO ai.agent_configuration_version(agent_configuration_version_id,
          agent_configuration_id,version_number,version_status,prompt_version_id,
          tool_set_version_id,retrieval_configuration_version_id,model_policy_version_id,published_at)
        VALUES ('81000000-0000-0000-0000-000000000010',
          '81000000-0000-0000-0000-000000000009',1,'PUBLISHED',
          '81000000-0000-0000-0000-000000000002',
          '81000000-0000-0000-0000-000000000004',
          '81000000-0000-0000-0000-000000000006',
          '81000000-0000-0000-0000-000000000008',now());
        UPDATE ai.feature_policy SET enabled_flag=true, maximum_tool_calls=2,
          maximum_output_tokens=1000, approval_status='APPROVED' WHERE scope_type='GLOBAL';
        INSERT INTO ai.conversation(conversation_id,tenant_id,conversation_type,user_id)
        VALUES ('{CONVERSATION_ID}','{TENANT_ID}','EMPLOYEE_HELPDESK','{USER_ID}');
        """
    )


@pytest.mark.integration
def test_policy_run_usage_version_references_and_tool_audit_are_durable() -> None:
    async def exercise() -> UUID:
        engine = create_async_engine(
            f"postgresql+psycopg://helpdesk_worker_login:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        context = RequestContext(
            UUID(TENANT_ID),
            UUID(USER_ID),
            "customer",
            frozenset({"CUSTOMER"}),
            frozenset(),
            None,
            "91000000-0000-0000-0000-000000000001",
            "ai-runtime-test",
        )
        async with factory() as session:
            async with session.begin():
                repository = AIRepository(session)
                policy = await repository.effective_policy(
                    context,
                    agent_code="EMPLOYEE_HELPDESK",
                    use_case_code="HELPDESK_CHAT",
                    environment_id=None,
                )
                run_id = await repository.start_run(context, UUID(CONVERSATION_ID), policy)
            async with session.begin():
                repository = AIRepository(session)
                result = LLMResult(
                    "safe",
                    (ToolRequest("1", "get_ticket_status", {"ticket_id": "HD-1"}),),
                    ModelUsage(10, 4, 1, Decimal("0.01"), "USD"),
                    "fake",
                    "fake-model",
                    "completed",
                )
                await repository.complete_run(context, run_id, policy, result, latency_ms=5)
                await repository.audit_tool_requested(context, run_id, "get_ticket_status")
                await repository.audit_tool(
                    context,
                    ToolAuditRecord(
                        run_id,
                        "get_ticket_status",
                        {"ticket_id": "HD-1"},
                        {"status": "OPEN"},
                        "ALLOWED",
                        "COMPLETED",
                    ),
                )
        await engine.dispose()
        return run_id

    run_id = asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop)
    assert (
        _psql(
            f"""
        SELECT run_status || ':' || input_tokens || ':' || output_tokens || ':' ||
          (prompt_version_id IS NOT NULL) || ':' || (model_policy_version_id IS NOT NULL)
        FROM ai.agent_run WHERE agent_run_id='{run_id}'
        """
        )
        == "COMPLETED:10:4:true:true"
    )
    assert _psql(f"SELECT count(*) FROM ai.usage_ledger WHERE agent_run_id='{run_id}'") == "1"
    assert _psql(f"SELECT count(*) FROM ai.tool_call WHERE agent_run_id='{run_id}'") == "1"
    assert (
        _psql(
            f"SELECT count(*) FROM audit.audit_event WHERE resource_id='{run_id}' "
            "AND action_code IN ('AI_TOOL_CALL_REQUESTED','AI_TOOL_CALL_RECORDED')"
        )
        == "2"
    )
    assert (
        _psql(
            """
        SELECT count(*) FROM information_schema.columns
        WHERE table_schema='ai'
          AND table_name IN ('feature_policy','model_policy','model_policy_version')
          AND (column_name LIKE '%api_key%' OR column_name LIKE '%credential%'
               OR column_name LIKE '%secret%')
        """
        )
        == "0"
    )


class _ExplodingProvider:
    provider_alias = "fake"

    def __init__(self, model_alias: str) -> None:
        self.model_alias = model_alias
        self.calls = 0

    async def generate(self, request: ProviderRequest) -> LLMResult:
        del request
        self.calls += 1
        raise AssertionError("an exhausted hard budget must not invoke a provider")


class _RecordingRegistry:
    def __init__(self, *providers: _ExplodingProvider) -> None:
        self._providers = {
            (provider.provider_alias, provider.model_alias): provider for provider in providers
        }
        self.resolutions: list[tuple[str, str]] = []

    def resolve(self, provider_alias: str, model_alias: str) -> _ExplodingProvider:
        self.resolutions.append((provider_alias, model_alias))
        return self._providers[(provider_alias, model_alias)]


def _enable_r2_ai_rls() -> None:
    _psql(
        """
        CREATE POLICY r2_tenant_or_global_ai_feature_policy ON ai.feature_policy
          USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id());
        CREATE POLICY r2_tenant_isolation_ai_usage_ledger ON ai.usage_ledger
          USING (tenant_id = util.current_tenant_id())
          WITH CHECK (tenant_id = util.current_tenant_id());
        ALTER TABLE ai.feature_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai.usage_ledger ENABLE ROW LEVEL SECURITY;
        """
    )


def _disable_r2_ai_rls() -> None:
    _psql(
        """
        ALTER TABLE ai.feature_policy DISABLE ROW LEVEL SECURITY;
        ALTER TABLE ai.usage_ledger DISABLE ROW LEVEL SECURITY;
        DROP POLICY r2_tenant_or_global_ai_feature_policy ON ai.feature_policy;
        DROP POLICY r2_tenant_isolation_ai_usage_ledger ON ai.usage_ledger;
        """
    )


@pytest.mark.integration
def test_exhausted_hard_budget_prevents_provider_execution_and_usage_charge() -> None:
    _psql(
        f"""
        INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
        VALUES ('{OTHER_TENANT_ID}','AI_RUNTIME_OTHER','Other AI runtime tenant')
        ON CONFLICT (tenant_id) DO NOTHING;
        UPDATE ai.feature_policy
        SET daily_budget=1,budget_currency='USD',hard_stop_threshold_percent=100
        WHERE scope_type='GLOBAL';
        INSERT INTO ai.usage_ledger(
          tenant_id,provider_alias,model_alias,use_case_code,estimated_cost,currency_code)
        VALUES ('{OTHER_TENANT_ID}','fake','foreign-model','PROVIDER_CALL',1000,'USD');
        """
    )
    _enable_r2_ai_rls()
    engine: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    context = RequestContext(
        UUID(TENANT_ID),
        UUID(USER_ID),
        "customer",
        frozenset({"CUSTOMER"}),
        frozenset(),
        None,
        "92000000-0000-0000-0000-000000000001",
        "ai-hard-budget-stop-test",
    )

    def factory(request_context: RequestContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessions, request_context, rls_enabled=True)

    primary = _ExplodingProvider("fake-model")
    fallback = _ExplodingProvider("fallback-model")
    registry = _RecordingRegistry(primary, fallback)

    async def forbidden_sleep(_: float) -> None:
        raise AssertionError("an exhausted hard budget must not retry")

    gateway = AIGateway(
        factory,
        Settings(
            ai_globally_enabled=True,
            openai_api_key=SecretStr("configuration-validation-only"),
            openai_model_aliases={"configured": "deployment"},
        ),
        cast("Any", registry),
        ResilientProviderExecutor(
            timeout_seconds=1,
            maximum_attempts=3,
            circuit_breaker=CircuitBreaker(2, 60),
            sleeper=forbidden_sleep,
        ),
    )

    async def exercise() -> tuple[str, str, str, str]:
        authorization = AuthorizationService()
        assert authorization.is_allowed(
            context,
            Permission.AI_EMPLOYEE_USE,
            AuthorizationResource(tenant_id=context.tenant_id),
        )
        async with factory(context) as uow:
            before_exhaustion = await AIRepository(uow.session).effective_policy(
                context,
                agent_code="EMPLOYEE_HELPDESK",
                use_case_code="HELPDESK_CHAT",
                environment_id=None,
            )
            await uow.commit()
        assert before_exhaustion.budget_remaining is True

        _psql(
            f"""
            INSERT INTO ai.usage_ledger(
              tenant_id,agent_configuration_id,user_id,provider_alias,model_alias,
              use_case_code,estimated_cost,currency_code)
            VALUES ('{TENANT_ID}','81000000-0000-0000-0000-000000000009','{USER_ID}',
              'fake','fake-model','PROVIDER_CALL',1,'USD');
            """
        )
        async with factory(context) as uow:
            exhausted = await AIRepository(uow.session).effective_policy(
                context,
                agent_code="EMPLOYEE_HELPDESK",
                use_case_code="HELPDESK_CHAT",
                environment_id=None,
            )
            await uow.commit()
        assert exhausted.budget_remaining is False

        snapshot = (
            _psql(f"SELECT count(*) FROM ai.agent_run WHERE conversation_id='{CONVERSATION_ID}'"),
            _psql(f"SELECT count(*) FROM ai.usage_ledger WHERE tenant_id='{TENANT_ID}'"),
            _psql(f"SELECT count(*) FROM audit.audit_event WHERE tenant_id='{TENANT_ID}'"),
            _psql(f"SELECT count(*) FROM audit.security_event WHERE tenant_id='{TENANT_ID}'"),
        )
        with pytest.raises(AIDisabledError, match="effective policy"):
            await gateway.generate_with_run(
                context,
                conversation_id=UUID(CONVERSATION_ID),
                agent_code="EMPLOYEE_HELPDESK",
                use_case_code="HELPDESK_CHAT",
                request=ProviderRequest("approved request", ()),
            )
        return snapshot

    try:
        runs_before, usage_before, audit_before, security_before = asyncio.run(
            exercise(), loop_factory=asyncio.SelectorEventLoop
        )

        assert registry.resolutions == []
        assert primary.calls == 0
        assert fallback.calls == 0
        assert (
            _psql(f"SELECT count(*) FROM ai.agent_run WHERE conversation_id='{CONVERSATION_ID}'")
            == runs_before
        )
        assert (
            _psql(f"SELECT count(*) FROM ai.usage_ledger WHERE tenant_id='{TENANT_ID}'")
            == usage_before
        )
        assert (
            _psql(f"SELECT count(*) FROM audit.audit_event WHERE tenant_id='{TENANT_ID}'")
            == audit_before
        )
        assert (
            _psql(f"SELECT count(*) FROM audit.security_event WHERE tenant_id='{TENANT_ID}'")
            == security_before
        )
    finally:
        asyncio.run(engine.dispose(), loop_factory=asyncio.SelectorEventLoop)
        _disable_r2_ai_rls()
