"""PostgreSQL validation for access-administration mutations (Task 11.5F).

Runs the real AdminService against a migrated database and verifies the
security invariants end to end: tenant isolation, self-mutation blocks,
grant boundaries, last-administrator protection with rollback, optimistic
concurrency, idempotent repeats, audit rows, denied-action security
events, and per-mutation statement ceilings.
"""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.app.admin.repository import AdminRepository
from apps.api.app.admin.schemas import (
    AdminQueueMemberRequest,
    AdminRoleAssignRequest,
    AdminUserStatusRequest,
)
from apps.api.app.admin.service import AdminService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
)
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.infrastructure.health import ApplicationResources

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-admin-access-test"
PORT = "55551"
DATABASE = "admin_access_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("20000000-0000-0000-0000-000000000099")
PLATFORM_ADMIN_ID = UUID("22000000-0000-0000-0000-000000000001")
PROJECT_ADMIN_ID = UUID("22000000-0000-0000-0000-000000000002")
SUPPORT_MANAGER_ID = UUID("22000000-0000-0000-0000-000000000003")
AGENT_ID = UUID("22000000-0000-0000-0000-000000000004")
CUSTOMER_ID = UUID("22000000-0000-0000-0000-000000000005")
INACTIVE_USER_ID = UUID("22000000-0000-0000-0000-000000000009")
OTHER_USER_ID = UUID("22000000-0000-0000-0000-000000000098")
FUSION_AP_GROUP_ID = UUID("23000000-0000-0000-0000-000000000002")
STATEMENT_CEILING = 8


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
def admin_access_database() -> Iterator[None]:
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


def _context(
    user_id: UUID, *, roles: tuple[str, ...] = ("PLATFORM_ADMIN",), tenant_id: UUID = TENANT_ID
) -> RequestContext:
    return RequestContext(
        tenant_id,
        user_id,
        f"subject-{user_id}",
        frozenset(roles),
        frozenset(),
        None,
        "corr-admin-access",
        "req-admin-access",
    )


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("""
            INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
            VALUES (:tenant_id,'OTHER','Other Tenant')
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {"tenant_id": OTHER_TENANT_ID},
    )
    await session.execute(
        text("""
            INSERT INTO identity.app_user(
              user_id,tenant_id,external_subject,email_address,display_name,active_flag)
            VALUES (:user_id,:tenant_id,'other-user','other@example.invalid',
              'Other Tenant User',true)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {"user_id": OTHER_USER_ID, "tenant_id": OTHER_TENANT_ID},
    )
    await session.commit()


async def _user_updated_at(session: AsyncSession, user_id: UUID) -> datetime:
    row = (
        await session.execute(
            text("SELECT updated_at FROM identity.app_user WHERE user_id=:user_id"),
            {"user_id": user_id},
        )
    ).one()
    return cast("datetime", row.updated_at)


async def _audit_actions(session: AsyncSession) -> list[str]:
    rows = (
        await session.execute(
            text("""
                SELECT action_code FROM audit.audit_event
                WHERE tenant_id=:tenant_id AND action_code LIKE 'ADMIN_%'
                ORDER BY audit_event_id
            """),
            {"tenant_id": TENANT_ID},
        )
    ).all()
    return [row.action_code for row in rows]


async def _security_event_types(session: AsyncSession) -> list[str]:
    rows = (
        await session.execute(
            text("""
                SELECT event_type FROM audit.security_event
                WHERE tenant_id=:tenant_id AND decision_code='DENIED'
                ORDER BY security_event_id
            """),
            {"tenant_id": TENANT_ID},
        )
    ).all()
    return [row.event_type for row in rows]


@pytest.mark.integration
@pytest.mark.anyio
async def test_access_mutations_enforce_invariants_and_audit() -> None:  # noqa: PLR0915
    engine: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn: object, cursor: object, sql: str, *args: object) -> None:
        statements.append(sql)

    maker = async_sessionmaker(engine, expire_on_commit=False)

    def factory(context: RequestContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(maker, context, rls_enabled=False)

    service = AdminService(factory, Settings(), cast("ApplicationResources", object()))
    admin_one = _context(PLATFORM_ADMIN_ID)
    try:
        async with maker() as session:
            await _seed(session)

        # Role assignment: happy path, idempotent repeat, statement ceiling.
        statements.clear()
        assigned = await service.assign_role(
            admin_one, CUSTOMER_ID, AdminRoleAssignRequest(role_code="AGENT")
        )
        assert assigned.changed and assigned.valid_from is not None
        assert len(statements) <= STATEMENT_CEILING, "role assignment budget"
        repeat = await service.assign_role(
            admin_one, CUSTOMER_ID, AdminRoleAssignRequest(role_code="AGENT")
        )
        assert repeat.changed is False
        assert repeat.valid_from == assigned.valid_from

        # Self, unknown-role, and cross-tenant targets fail closed.
        with pytest.raises(AuthorizationError):
            await service.assign_role(
                admin_one, PLATFORM_ADMIN_ID, AdminRoleAssignRequest(role_code="AGENT")
            )
        with pytest.raises(NotFoundError):
            await service.assign_role(
                admin_one, CUSTOMER_ID, AdminRoleAssignRequest(role_code="NOT_A_ROLE")
            )
        with pytest.raises(NotFoundError):
            await service.assign_role(
                admin_one, OTHER_USER_ID, AdminRoleAssignRequest(role_code="AGENT")
            )

        # Grant boundary: a weaker administrator cannot hand out a stronger role.
        weaker = _context(SUPPORT_MANAGER_ID, roles=("SUPPORT_MANAGER",))
        with pytest.raises(AuthorizationError):
            await service.assign_role(
                weaker, CUSTOMER_ID, AdminRoleAssignRequest(role_code="PLATFORM_ADMIN")
            )

        # Role removal: happy path, idempotent repeat, re-grant creates a new window.
        statements.clear()
        removed = await service.remove_role(admin_one, CUSTOMER_ID, "AGENT")
        assert removed.changed is True
        assert len(statements) <= STATEMENT_CEILING, "role removal budget"
        assert (await service.remove_role(admin_one, CUSTOMER_ID, "AGENT")).changed is False
        regrant = await service.assign_role(
            admin_one, CUSTOMER_ID, AdminRoleAssignRequest(role_code="AGENT")
        )
        assert regrant.changed and regrant.valid_from != assigned.valid_from

        # Last-administrator protection for role removal, with rollback proof.
        second_admin = await service.assign_role(
            admin_one, PROJECT_ADMIN_ID, AdminRoleAssignRequest(role_code="PLATFORM_ADMIN")
        )
        assert second_admin.changed is True
        admin_two = _context(PROJECT_ADMIN_ID)
        demoted = await service.remove_role(admin_two, PLATFORM_ADMIN_ID, "PLATFORM_ADMIN")
        assert demoted.changed is True, "removal is allowed while another admin survives"
        with pytest.raises(AuthorizationError):
            await service.remove_role(admin_two, PROJECT_ADMIN_ID, "PLATFORM_ADMIN")
        with pytest.raises(ConflictError):
            await service.remove_role(admin_one, PROJECT_ADMIN_ID, "PLATFORM_ADMIN")
        async with maker() as session:
            still_admin = await AdminRepository(session).active_role_assignment(
                TENANT_ID, PROJECT_ADMIN_ID, "PLATFORM_ADMIN"
            )
            assert still_admin is not None, "conflict must roll back nothing-committed state"

        # Last-administrator protection for deactivation.
        async with maker() as session:
            token = await _user_updated_at(session, PROJECT_ADMIN_ID)
        with pytest.raises(ConflictError):
            await service.set_user_status(
                admin_one,
                PROJECT_ADMIN_ID,
                AdminUserStatusRequest(active=False, expected_updated_at=token),
            )

        # Status mutations: deactivate, idempotent repeat, stale token, reactivate.
        async with maker() as session:
            customer_token = await _user_updated_at(session, CUSTOMER_ID)
        statements.clear()
        deactivated = await service.set_user_status(
            admin_two,
            CUSTOMER_ID,
            AdminUserStatusRequest(active=False, expected_updated_at=customer_token),
        )
        assert deactivated.changed is True and deactivated.active_flag is False
        assert len(statements) <= STATEMENT_CEILING, "status mutation budget"
        same_state = await service.set_user_status(
            admin_two,
            CUSTOMER_ID,
            AdminUserStatusRequest(active=False, expected_updated_at=customer_token),
        )
        assert same_state.changed is False
        with pytest.raises(ConcurrencyError):
            await service.set_user_status(
                admin_two,
                CUSTOMER_ID,
                AdminUserStatusRequest(active=True, expected_updated_at=customer_token),
            )
        reactivated = await service.set_user_status(
            admin_two,
            CUSTOMER_ID,
            AdminUserStatusRequest(active=True, expected_updated_at=deactivated.updated_at),
        )
        assert reactivated.changed is True and reactivated.active_flag is True
        with pytest.raises(AuthorizationError):
            await service.set_user_status(
                admin_two,
                PROJECT_ADMIN_ID,
                AdminUserStatusRequest(active=False, expected_updated_at=reactivated.updated_at),
            )
        with pytest.raises(NotFoundError):
            await service.set_user_status(
                admin_one,
                OTHER_USER_ID,
                AdminUserStatusRequest(active=False, expected_updated_at=reactivated.updated_at),
            )
        idempotent_inactive = await service.set_user_status(
            admin_one,
            INACTIVE_USER_ID,
            AdminUserStatusRequest(active=False, expected_updated_at=reactivated.updated_at),
        )
        assert idempotent_inactive.changed is False

        # Queue membership: add, same-state repeat, role change, remove, repeats.
        statements.clear()
        added = await service.add_queue_member(
            admin_one,
            FUSION_AP_GROUP_ID,
            AdminQueueMemberRequest(user_id=CUSTOMER_ID, member_role="OBSERVER"),
        )
        assert added.changed is True
        assert len(statements) <= STATEMENT_CEILING, "queue member add budget"
        same_member = await service.add_queue_member(
            admin_one,
            FUSION_AP_GROUP_ID,
            AdminQueueMemberRequest(user_id=CUSTOMER_ID, member_role="OBSERVER"),
        )
        assert same_member.changed is False
        promoted = await service.add_queue_member(
            admin_one,
            FUSION_AP_GROUP_ID,
            AdminQueueMemberRequest(user_id=CUSTOMER_ID, member_role="LEAD"),
        )
        assert promoted.changed is True
        statements.clear()
        removed_member = await service.remove_queue_member(
            admin_one, FUSION_AP_GROUP_ID, CUSTOMER_ID
        )
        assert removed_member.changed is True
        assert len(statements) <= STATEMENT_CEILING, "queue member remove budget"
        assert (
            await service.remove_queue_member(admin_one, FUSION_AP_GROUP_ID, CUSTOMER_ID)
        ).changed is False
        with pytest.raises(NotFoundError):
            await service.add_queue_member(
                admin_one,
                uuid4(),
                AdminQueueMemberRequest(user_id=CUSTOMER_ID, member_role="AGENT"),
            )
        with pytest.raises(NotFoundError):
            await service.add_queue_member(
                admin_one,
                FUSION_AP_GROUP_ID,
                AdminQueueMemberRequest(user_id=OTHER_USER_ID, member_role="AGENT"),
            )
        with pytest.raises(NotFoundError):
            await service.remove_queue_member(
                _context(OTHER_USER_ID, tenant_id=OTHER_TENANT_ID),
                FUSION_AP_GROUP_ID,
                CUSTOMER_ID,
            )

        # Audit rows exist for every applied change and only safe fields appear.
        async with maker() as session:
            actions = await _audit_actions(session)
            for expected in (
                "ADMIN_ROLE_ASSIGNED",
                "ADMIN_ROLE_REMOVED",
                "ADMIN_USER_DEACTIVATED",
                "ADMIN_USER_REACTIVATED",
                "ADMIN_QUEUE_MEMBER_ADDED",
                "ADMIN_QUEUE_MEMBER_REMOVED",
            ):
                assert expected in actions, expected
            summaries = (
                await session.execute(
                    text("""
                        SELECT change_summary_json::text AS summary
                        FROM audit.audit_event
                        WHERE tenant_id=:tenant_id AND action_code LIKE 'ADMIN_%'
                    """),
                    {"tenant_id": TENANT_ID},
                )
            ).all()
            for row in summaries:
                lowered = row.summary.lower()
                for fragment in ("password", "token", "secret", "issuer", "subject"):
                    assert fragment not in lowered

            # Denied attempts are security-evented even though nothing committed.
            denied = await _security_event_types(session)
            for expected in (
                "ADMIN_SELF_MUTATION_BLOCKED",
                "ADMIN_ROLE_GRANT_BOUNDARY_BLOCKED",
                "LAST_ADMIN_PROTECTION_TRIGGERED",
            ):
                assert expected in denied, expected
    finally:
        await engine.dispose()
