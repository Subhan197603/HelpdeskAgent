"""PostgreSQL validation for read-only identity administration reads (Task 11.5B).

Seeds a second tenant, an OIDC-linked identity, and security events on top of
the deterministic personas and catalogue, then verifies tenant isolation,
filtering, ordering, and the one-statement budgets of the users, roles,
queues, and ticket-view reads.
"""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.admin.repository import AdminRepository, escape_like_pattern

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-admin-identity-test"
PORT = "55554"
DATABASE = "admin_identity_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("20000000-0000-0000-0000-000000000099")
PLATFORM_ADMIN_ID = UUID("22000000-0000-0000-0000-000000000001")
SUPPORT_MANAGER_ID = UUID("22000000-0000-0000-0000-000000000003")
AGENT_ID = UUID("22000000-0000-0000-0000-000000000004")
AGENT_TWO_ID = UUID("22000000-0000-0000-0000-000000000012")
OTHER_USER_ID = UUID("22000000-0000-0000-0000-000000000098")
SERVICE_DESK_GROUP_ID = UUID("23000000-0000-0000-0000-000000000001")
FUSION_AP_GROUP_ID = UUID("23000000-0000-0000-0000-000000000002")
MAPPING_ID = UUID("24000000-0000-0000-0000-000000000001")
BASE_TIME = datetime(2030, 6, 15, 12, 0, tzinfo=UTC)


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


@pytest.fixture(scope="module", autouse=True)
def admin_identity_database() -> Iterator[None]:
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
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


async def _seed(session: object) -> None:
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
            VALUES (:tenant_id,'OTHER','Other Tenant')
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {"tenant_id": OTHER_TENANT_ID},
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO identity.app_user(
              user_id,tenant_id,external_subject,email_address,display_name,active_flag)
            VALUES (:user_id,:tenant_id,'other-user','other@example.invalid',
              'Other Tenant User',true)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {"user_id": OTHER_USER_ID, "tenant_id": OTHER_TENANT_ID},
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO identity.oidc_tenant_mapping(
              oidc_tenant_mapping_id,tenant_id,provider_code,trusted_issuer)
            VALUES (:mapping_id,:tenant_id,'KEYCLOAK_LOCAL','https://keycloak.invalid/realms/dev')
            ON CONFLICT (oidc_tenant_mapping_id) DO NOTHING
        """),
        {"mapping_id": MAPPING_ID, "tenant_id": TENANT_ID},
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO identity.external_identity(
              tenant_id,oidc_tenant_mapping_id,user_id,external_subject,
              active_flag,last_authenticated_at)
            VALUES (:tenant_id,:mapping_id,:user_id,'kc-platform-admin',true,:authenticated_at)
            ON CONFLICT (oidc_tenant_mapping_id,user_id) DO NOTHING
        """),
        {
            "tenant_id": TENANT_ID,
            "mapping_id": MAPPING_ID,
            "user_id": PLATFORM_ADMIN_ID,
            "authenticated_at": BASE_TIME,
        },
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            UPDATE identity.support_group SET manager_user_id=:manager_id
            WHERE support_group_id=:group_id
        """),
        {"manager_id": SUPPORT_MANAGER_ID, "group_id": SERVICE_DESK_GROUP_ID},
    )
    security_rows = [
        ("PRIVILEGED_ENDPOINT_ACCESSED", "ALLOWED", 2),
        ("AUTHORIZATION_DENIED", "DENIED", 1),
        ("AUTHORIZATION_DENIED", "DENIED", 0),
    ]
    for event_type, decision, hour_offset in security_rows:
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO audit.security_event(
                  tenant_id,user_id,event_type,resource_type,resource_id,
                  decision_code,event_data_json,occurred_at)
                VALUES (:tenant_id,:user_id,:event_type,'endpoint',
                  '/api/v1/admin/users',:decision,'{"detail":"seed"}',:occurred_at)
            """),
            {
                "tenant_id": TENANT_ID,
                "user_id": PLATFORM_ADMIN_ID,
                "event_type": event_type,
                "decision": decision,
                "occurred_at": BASE_TIME + timedelta(hours=hour_offset),
            },
        )
    await session.commit()  # type: ignore[attr-defined]


def test_escape_like_pattern_neutralises_wildcards() -> None:
    assert escape_like_pattern(None) is None
    assert escape_like_pattern("plain") == "%plain%"
    assert escape_like_pattern("50%_x\\y") == "%50\\%\\_x\\\\y%"


@pytest.mark.integration
@pytest.mark.anyio
async def test_identity_reads_are_tenant_scoped_filtered_and_budgeted() -> None:
    engine: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn: object, cursor: object, sql: str, *args: object) -> None:
        statements.append(sql)

    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await _seed(session)
        async with maker() as session:
            repository = AdminRepository(session)

            statements.clear()
            users = await repository.users(
                TENANT_ID,
                search=None,
                active=None,
                role_code=None,
                support_group_id=None,
                provider_code=None,
                limit=50,
                offset=0,
            )
            assert len(statements) == 1, "user list budget is one statement"
            assert len(users) == 10, "other-tenant users are excluded"
            assert [user.display_name for user in users[:2]] == [
                "Development Agent",
                "Development Agent Two",
            ]
            admin = next(user for user in users if user.user_id == PLATFORM_ADMIN_ID)
            assert admin.role_codes == ("PLATFORM_ADMIN",)
            assert admin.identity_provider_codes == ("KEYCLOAK_LOCAL",)
            assert admin.business_unit_name == "Local Development"
            agent = next(user for user in users if user.user_id == AGENT_ID)
            assert agent.support_group_names == (
                "Development Service Desk",
                "Fusion Accounts Payable Support",
            )

            searched = await repository.users(
                TENANT_ID,
                search="Agent",
                active=None,
                role_code=None,
                support_group_id=None,
                provider_code=None,
                limit=50,
                offset=0,
            )
            assert [user.user_id for user in searched] == [AGENT_ID, AGENT_TWO_ID]

            wildcard = await repository.users(
                TENANT_ID,
                search="%",
                active=None,
                role_code=None,
                support_group_id=None,
                provider_code=None,
                limit=50,
                offset=0,
            )
            assert wildcard == (), "LIKE wildcards in search input are neutralised"

            inactive = await repository.users(
                TENANT_ID,
                search=None,
                active=False,
                role_code=None,
                support_group_id=None,
                provider_code=None,
                limit=50,
                offset=0,
            )
            assert [user.display_name for user in inactive] == ["Development Inactive User"]

            by_role = await repository.users(
                TENANT_ID,
                search=None,
                active=None,
                role_code="AGENT",
                support_group_id=None,
                provider_code=None,
                limit=50,
                offset=0,
            )
            assert [user.user_id for user in by_role] == [AGENT_ID, AGENT_TWO_ID]

            by_group = await repository.users(
                TENANT_ID,
                search=None,
                active=None,
                role_code=None,
                support_group_id=FUSION_AP_GROUP_ID,
                provider_code=None,
                limit=50,
                offset=0,
            )
            assert [user.user_id for user in by_group] == [
                AGENT_ID,
                AGENT_TWO_ID,
                SUPPORT_MANAGER_ID,
            ]

            by_provider = await repository.users(
                TENANT_ID,
                search=None,
                active=None,
                role_code=None,
                support_group_id=None,
                provider_code="KEYCLOAK_LOCAL",
                limit=50,
                offset=0,
            )
            assert [user.user_id for user in by_provider] == [PLATFORM_ADMIN_ID]

            profile = await repository.user_profile(TENANT_ID, PLATFORM_ADMIN_ID)
            assert profile is not None
            assert profile.external_subject == "platform-admin"
            assert len(profile.external_identities) == 1
            identity = profile.external_identities[0]
            assert identity.provider_code == "KEYCLOAK_LOCAL"
            assert identity.active_flag is True
            assert identity.last_authenticated_at is not None
            assert await repository.user_profile(OTHER_TENANT_ID, PLATFORM_ADMIN_ID) is None

            roles_for_user = await repository.user_roles(TENANT_ID, SUPPORT_MANAGER_ID)
            assert [role.role_code for role in roles_for_user] == ["SUPPORT_MANAGER"]
            assert roles_for_user[0].role_name

            memberships = await repository.user_memberships(TENANT_ID, SUPPORT_MANAGER_ID)
            assert [(member.group_name, member.member_role) for member in memberships] == [
                ("Development Service Desk", "MANAGER"),
                ("Fusion Accounts Payable Support", "OBSERVER"),
            ]

            recent = await repository.user_security_events(TENANT_ID, PLATFORM_ADMIN_ID, limit=2)
            assert [row.event_type for row in recent] == [
                "PRIVILEGED_ENDPOINT_ACCESSED",
                "AUTHORIZATION_DENIED",
            ]
            assert (
                await repository.user_security_events(OTHER_TENANT_ID, PLATFORM_ADMIN_ID, limit=10)
                == ()
            )

            statements.clear()
            roles = await repository.roles(TENANT_ID, search=None, limit=50, offset=0)
            assert len(statements) == 1, "role list budget is one statement"
            by_code = {role.role_code: role for role in roles}
            assert by_code["PLATFORM_ADMIN"].assigned_user_count == 1
            assert by_code["CUSTOMER"].assigned_user_count == 2
            assert by_code["AGENT"].assigned_user_count == 2

            searched_roles = await repository.roles(TENANT_ID, search="agent", limit=50, offset=0)
            assert [role.role_code for role in searched_roles] == ["AGENT"]

            role = await repository.role("PLATFORM_ADMIN")
            assert role is not None and role.system_role_flag is True
            assert await repository.role("NOT_A_ROLE") is None

            assignments = await repository.role_assignments(TENANT_ID, "AGENT", limit=50, offset=0)
            assert [assignment.user_id for assignment in assignments] == [AGENT_ID, AGENT_TWO_ID]
            assert (
                await repository.role_assignments(OTHER_TENANT_ID, "AGENT", limit=50, offset=0)
                == ()
            )

            statements.clear()
            queues = await repository.queues(
                TENANT_ID, search=None, active=None, limit=50, offset=0
            )
            assert len(statements) == 1, "queue list budget is one statement"
            assert [(queue.group_code, queue.member_count) for queue in queues] == [
                ("DEV_SERVICE_DESK", 2),
                ("FUSION_AP", 3),
            ]

            searched_queues = await repository.queues(
                TENANT_ID, search="fusion", active=None, limit=50, offset=0
            )
            assert [queue.group_code for queue in searched_queues] == ["FUSION_AP"]

            queue = await repository.queue(TENANT_ID, SERVICE_DESK_GROUP_ID)
            assert queue is not None
            assert queue.manager_display_name == "Development Support Manager"
            assert await repository.queue(OTHER_TENANT_ID, SERVICE_DESK_GROUP_ID) is None

            members = await repository.queue_members(TENANT_ID, FUSION_AP_GROUP_ID)
            assert [(member.display_name, member.member_role) for member in members] == [
                ("Development Agent", "AGENT"),
                ("Development Agent Two", "AGENT"),
                ("Development Support Manager", "OBSERVER"),
            ]

            statements.clear()
            views = await repository.ticket_views(
                TENANT_ID, owner_group_id=None, limit=50, offset=0
            )
            assert len(statements) == 1, "ticket view list budget is one statement"
            assert [view.queue_name for view in views] == [
                "Unassigned",
                "Assigned to me",
                "Fusion AP group",
                "ERP project",
            ]
            assert {view.version_status for view in views} == {"PUBLISHED"}

            owned = await repository.ticket_views(
                TENANT_ID, owner_group_id=FUSION_AP_GROUP_ID, limit=50, offset=0
            )
            assert [view.queue_name for view in owned] == ["Fusion AP group"]
            assert owned[0].visibility == "GROUP"
            assert (
                await repository.ticket_views(
                    OTHER_TENANT_ID, owner_group_id=None, limit=50, offset=0
                )
                == ()
            )
    finally:
        await engine.dispose()
