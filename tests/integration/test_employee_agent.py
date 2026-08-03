"""PostgreSQL validation for Task 8.2 employee conversations and turns."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.employee_agent.models import AgentAnswer, AgentState, TurnOutcome
from apps.api.app.employee_agent.repository import (
    ActiveTurnError,
    ConversationNotFoundError,
    EmployeeAgentRepository,
)
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-employee-agent-test"
PORT = "55458"
DATABASE = "employee_agent"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
USER_ID = UUID("22000000-0000-0000-0000-000000000005")


class _HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


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
            "/development/catalogue.sql",
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
    _migrate("downgrade", "0017_employee_agent")
    assert (
        _psql(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='itsm' "
            "AND table_name='ticket_draft' AND column_name='source_conversation_id'"
        )
        == "0"
    )
    _migrate("downgrade", "0016_retrieval_fusion")
    assert _psql("SELECT to_regclass('ai.conversation_turn')") == ""
    _migrate("upgrade", "head")
    assert _psql("SELECT to_regclass('ai.conversation_turn')") == "ai.conversation_turn"
    assert _psql("SELECT version_num FROM config.alembic_version") == "0018_agent_escalation"


def _api_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "test",
            "database_url": (f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"),
            "redis_url": "redis://localhost:6379/15",
            "trusted_hosts": ["testserver"],
            "developer_identity_enabled": True,
        }
    )


def _api_resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(
        Database(settings), _HealthyProbe(), _HealthyProbe(), _HealthyProbe()
    )


def _conversation(state: str) -> UUID:
    conversation_id = uuid4()
    _psql(
        f"""
        INSERT INTO ai.conversation(
          conversation_id,tenant_id,conversation_type,user_id,metadata_json)
        VALUES ('{conversation_id}','{TENANT_ID}','EMPLOYEE_HELPDESK','{USER_ID}',
          jsonb_build_object('state','{state}'));
        INSERT INTO ai.message(conversation_id,role_code,content_text)
        VALUES ('{conversation_id}','USER','Invoice validation fails with error AP-204.');
        """
    )
    return conversation_id


@pytest.mark.integration
def test_feedback_review_confirmation_and_backend_ticket_linkage() -> None:
    conversation_id = _conversation("AWAITING_RESOLUTION_CONFIRMATION")
    headers = {"X-Developer-User": "DEV/customer"}
    app = create_app(_api_settings(), resource_factory=_api_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        feedback = client.post(
            f"/api/v1/assistant/conversations/{conversation_id}/resolution-feedback",
            headers=headers,
            json={
                "helpful": False,
                "resolved": False,
                "comment": "The suggested steps did not work.",
                "draft": {
                    "request_type_id": "33000000-0000-0000-0000-000000000001",
                    "summary": "Fusion invoice validation failure",
                    "description": "The AP invoice cannot be validated.",
                    "impact": "LIMITED",
                    "urgency": "NORMAL",
                    "custom_fields": [{"field_code": "environment", "value": "PROD"}],
                },
            },
        )
        assert feedback.status_code == 200, feedback.text
        draft = feedback.json()["draft"]
        assert draft["status"] == "DRAFT"
        assert "Bounded employee conversation summary" in draft["description"]
        assert _psql("SELECT count(*) FROM itsm.ticket") == "0"

        updated = client.patch(
            f"/api/v1/ticket-drafts/{draft['id']}",
            headers=headers,
            json={
                "summary": "Reviewed Fusion invoice validation failure",
                "row_version": draft["row_version"],
            },
        )
        assert updated.status_code == 200, updated.text
        reviewed = client.post(
            f"/api/v1/ticket-drafts/{draft['id']}/validate",
            headers=headers,
            json={"row_version": updated.json()["row_version"]},
        )
        assert reviewed.status_code == 200, reviewed.text
        reviewed_draft = reviewed.json()["draft"]

        missing_confirmation = client.post(
            f"/api/v1/assistant/conversations/{conversation_id}/confirm-ticket",
            headers=headers,
            json={"row_version": reviewed_draft["row_version"]},
        )
        assert missing_confirmation.status_code == 422
        assert _psql("SELECT count(*) FROM itsm.ticket") == "0"

        confirmation_headers = {**headers, "Idempotency-Key": "agent-confirm-invoice-1"}
        confirmed = client.post(
            f"/api/v1/assistant/conversations/{conversation_id}/confirm-ticket",
            headers=confirmation_headers,
            json={"row_version": reviewed_draft["row_version"]},
        )
        assert confirmed.status_code == 201, confirmed.text
        replay = client.post(
            f"/api/v1/assistant/conversations/{conversation_id}/confirm-ticket",
            headers=confirmation_headers,
            json={"row_version": reviewed_draft["row_version"]},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["ticket"]["key"] == confirmed.json()["ticket"]["key"]

    assert _psql("SELECT count(*) FROM itsm.ticket") == "1"
    assert (
        _psql(
            f"SELECT ai_created_flag || ':' || channel_code || ':' || priority_code "
            f"FROM itsm.ticket WHERE source_conversation_id='{conversation_id}'"
        )
        == "true:CHAT:P4"
    )
    assert (
        _psql(
            f"SELECT metadata_json->>'state' FROM ai.conversation "
            f"WHERE conversation_id='{conversation_id}'"
        )
        == "TICKET_SUBMITTED"
    )
    assert (
        _psql(
            f"SELECT count(*) FROM ai.feedback WHERE conversation_id='{conversation_id}' "
            "AND rating_value=1 AND resolved_issue_flag=false"
        )
        == "1"
    )


@pytest.mark.integration
def test_resolved_feedback_closes_without_draft_or_ticket() -> None:
    conversation_id = _conversation("AWAITING_RESOLUTION_CONFIRMATION")
    before = int(_psql("SELECT count(*) FROM itsm.ticket"))
    app = create_app(_api_settings(), resource_factory=_api_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        response = client.post(
            f"/api/v1/assistant/conversations/{conversation_id}/resolution-feedback",
            headers={"X-Developer-User": "DEV/customer"},
            json={"helpful": True, "resolved": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "RESOLVED_WITHOUT_TICKET"
    assert int(_psql("SELECT count(*) FROM itsm.ticket")) == before
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_draft "
            f"WHERE source_conversation_id='{conversation_id}'"
        )
        == "0"
    )
