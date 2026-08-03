"""PostgreSQL validation for Task 8.2 employee conversations and turns."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.core.context import RequestContext
from apps.api.app.employee_agent.models import AgentAnswer, AgentState, TurnOutcome
from apps.api.app.employee_agent.repository import (
    ActiveTurnError,
    ConversationNotFoundError,
    EmployeeAgentRepository,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-employee-agent-test"
PORT = "55458"
DATABASE = "employee_agent"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
USER_ID = UUID("22000000-0000-0000-0000-000000000005")


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
def employee_agent_database() -> Iterator[None]:
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
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _context(user_id: UUID = USER_ID) -> RequestContext:
    return RequestContext(
        TENANT_ID,
        user_id,
        "employee",
        frozenset({"CUSTOMER"}),
        frozenset(),
        None,
        str(uuid4()),
        "employee-agent-integration",
    )


@pytest.mark.integration
def test_owned_turn_lifecycle_active_turn_guard_and_cross_user_isolation() -> None:
    async def exercise() -> tuple[UUID, UUID]:
        engine = create_async_engine(
            f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        context = _context()
        try:
            async with sessions() as session, session.begin():
                conversation = await EmployeeAgentRepository(session).create(context)
            async with sessions() as session, session.begin():
                repository = EmployeeAgentRepository(session)
                owned = await repository.owned(context, conversation.conversation_id)
                started = await repository.start_turn(
                    context, conversation.conversation_id, "Reset my password", history_limit=8
                )
                assert owned.state is AgentState.NEW
                assert await repository.turn_active(
                    context, conversation.conversation_id, started.turn_id
                )
            async with sessions() as session, session.begin():
                with pytest.raises(ActiveTurnError):
                    await EmployeeAgentRepository(session).start_turn(
                        context, conversation.conversation_id, "duplicate", history_limit=8
                    )
            async with sessions() as session, session.begin():
                await EmployeeAgentRepository(session).finish_turn(
                    context,
                    conversation.conversation_id,
                    started.turn_id,
                    AgentAnswer(
                        "Use the approved password reset guide.",
                        AgentState.AWAITING_RESOLUTION_CONFIRMATION,
                        TurnOutcome.RESOLUTION_PROPOSED,
                    ),
                )
            async with sessions() as session, session.begin():
                assert not await EmployeeAgentRepository(session).turn_active(
                    context, conversation.conversation_id, started.turn_id
                )
                with pytest.raises(ConversationNotFoundError):
                    await EmployeeAgentRepository(session).owned(
                        _context(UUID("22000000-0000-0000-0000-000000000004")),
                        conversation.conversation_id,
                    )
            return conversation.conversation_id, started.turn_id
        finally:
            await engine.dispose()

    conversation_id, turn_id = asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop)
    assert (
        _psql(
            f"SELECT turn_status || ':' || state_code FROM ai.conversation_turn "
            f"WHERE conversation_turn_id='{turn_id}'"
        )
        == "COMPLETED:AWAITING_RESOLUTION_CONFIRMATION"
    )
    assert (
        _psql(f"SELECT count(*) FROM ai.message WHERE conversation_id='{conversation_id}'") == "2"
    )
    assert (
        _psql(
            f"SELECT count(*) FROM audit.audit_event WHERE resource_id='{turn_id}' "
            "AND action_code='AI_CONVERSATION_TURN_COMPLETED'"
        )
        == "1"
    )


@pytest.mark.integration
def test_turn_migration_downgrade_and_reupgrade_remain_linear() -> None:
    _migrate("downgrade", "0016_retrieval_fusion")
    assert _psql("SELECT to_regclass('ai.conversation_turn')") == ""
    _migrate("upgrade", "head")
    assert _psql("SELECT to_regclass('ai.conversation_turn')") == "ai.conversation_turn"
    assert _psql("SELECT version_num FROM config.alembic_version") == "0017_employee_agent"
