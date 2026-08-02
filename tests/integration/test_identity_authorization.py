"""Developer identity, authorization, transaction context, and optional RLS tests."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.oidc import (
    AuthenticationMetrics,
    OidcTokenValidator,
    ValidatedOidcIdentity,
)
from apps.api.app.identity.oidc_service import OidcIdentityService
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PROJECT = "fusion-helpdesk-identity-test"
POSTGRES_PORT = "55442"
DATABASES = ("identity_auth", "identity_rls")


class HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = POSTGRES_PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", "compose", "--project-name", COMPOSE_PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and completed.returncode != 0:
        pytest.fail(
            f"Docker Compose failed ({completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _psql(database: str, *arguments: str) -> str:
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
        database,
        *arguments,
    ).stdout.strip()


def _admin_url(database: str) -> str:
    return f"postgresql+psycopg://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/{database}"


def _app_url(database: str) -> str:
    return f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{POSTGRES_PORT}/{database}"


def _migrate(database: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "integration",
            "MIGRATION_DATABASE_URL": _admin_url(database),
        }
    )
    for command in ("stamp", "upgrade"):
        completed = subprocess.run(
            ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", command],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            pytest.fail(completed.stdout + completed.stderr)


@pytest.fixture(scope="module", autouse=True)
def identity_databases() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        for database in DATABASES:
            _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", database)
            _psql(database, "-f", "/baseline/install_all.sql")
            _psql(
                database,
                "-v",
                "app_password=helpdesk",
                "-f",
                "/runtime-config/configure_local_runtime.sql",
            )
            _migrate(database)
            _psql(database, "-f", "/development/identity_personas.sql")

        _psql(
            "identity_auth",
            "-c",
            """
            INSERT INTO identity.tenant(tenant_id, tenant_code, tenant_name)
            VALUES ('20000000-0000-0000-0000-000000000002', 'OTHER', 'Other Test Tenant');
            INSERT INTO identity.app_user(
                user_id, tenant_id, external_subject, email_address, display_name
            ) VALUES (
                '22000000-0000-0000-0000-000000000010',
                '20000000-0000-0000-0000-000000000002',
                'customer', 'other-customer@example.invalid', 'Other Customer'
            );
            INSERT INTO identity.user_role(tenant_id, user_id, role_code, valid_from)
            VALUES (
                '20000000-0000-0000-0000-000000000002',
                '22000000-0000-0000-0000-000000000010',
                'CUSTOMER', '2025-01-01T00:00:00Z'
            );
            INSERT INTO identity.user_role(
                tenant_id, user_id, role_code, valid_from, active_flag
            ) VALUES (
                '20000000-0000-0000-0000-000000000001',
                '22000000-0000-0000-0000-000000000004',
                'PLATFORM_ADMIN', '2025-01-02T00:00:00Z', false
            );
            INSERT INTO identity.user_role(
                tenant_id, user_id, role_code, valid_from, valid_to
            ) VALUES (
                '20000000-0000-0000-0000-000000000001',
                '22000000-0000-0000-0000-000000000004',
                'PROJECT_ADMIN', '2024-01-01T00:00:00Z', '2024-02-01T00:00:00Z'
            );
            INSERT INTO identity.tenant(
                tenant_id, tenant_code, tenant_name, active_flag
            ) VALUES (
                '20000000-0000-0000-0000-000000000003',
                'INACTIVE', 'Inactive Test Tenant', false
            );
            INSERT INTO identity.app_user(
                user_id, tenant_id, external_subject, email_address, display_name
            ) VALUES (
                '22000000-0000-0000-0000-000000000011',
                '20000000-0000-0000-0000-000000000003',
                'customer', 'inactive-tenant@example.invalid', 'Inactive Tenant Customer'
            );
            INSERT INTO identity.oidc_tenant_mapping(
                oidc_tenant_mapping_id, tenant_id, provider_code, trusted_issuer,
                organization_claim_value
            ) VALUES
                (
                    '24000000-0000-0000-0000-000000000001',
                    '20000000-0000-0000-0000-000000000001',
                    'TEST_OIDC', 'https://identity.example.test/issuer', 'dev-org'
                ),
                (
                    '24000000-0000-0000-0000-000000000002',
                    '20000000-0000-0000-0000-000000000002',
                    'TEST_OIDC', 'https://identity.example.test/issuer', 'other-org'
                );
            INSERT INTO identity.external_identity(
                external_identity_id, tenant_id, oidc_tenant_mapping_id,
                user_id, external_subject
            ) VALUES
                (
                    '25000000-0000-0000-0000-000000000001',
                    '20000000-0000-0000-0000-000000000001',
                    '24000000-0000-0000-0000-000000000001',
                    '22000000-0000-0000-0000-000000000004', 'oidc-agent'
                ),
                (
                    '25000000-0000-0000-0000-000000000002',
                    '20000000-0000-0000-0000-000000000002',
                    '24000000-0000-0000-0000-000000000002',
                    '22000000-0000-0000-0000-000000000010', 'oidc-other'
                );
            """,
        )
        _psql("identity_rls", "-f", "/baseline/09_optional_rls.sql")
        _psql(
            "identity_rls",
            "-c",
            """
            INSERT INTO identity.oidc_tenant_mapping(
                oidc_tenant_mapping_id, tenant_id, provider_code, trusted_issuer,
                organization_claim_value
            ) VALUES (
                '24000000-0000-0000-0000-000000000011',
                '20000000-0000-0000-0000-000000000001',
                'TEST_OIDC', 'https://identity.example.test/issuer', 'dev-org'
            );
            INSERT INTO identity.external_identity(
                external_identity_id, tenant_id, oidc_tenant_mapping_id,
                user_id, external_subject
            ) VALUES (
                '25000000-0000-0000-0000-000000000011',
                '20000000-0000-0000-0000-000000000001',
                '24000000-0000-0000-0000-000000000011',
                '22000000-0000-0000-0000-000000000004', 'oidc-agent'
            );
            """,
        )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _settings(database: str, *, rls_enabled: bool = False) -> Settings:
    return Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": _app_url(database),
            "developer_identity_enabled": True,
            "rls_enabled": rls_enabled,
            "object_storage_enabled": False,
            "trusted_hosts": ["testserver"],
        }
    )


def _resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(Database(settings), HealthyProbe(), HealthyProbe(), HealthyProbe())


class StubOidcTokenValidator(OidcTokenValidator):
    def __init__(self, identities: dict[str, ValidatedOidcIdentity]) -> None:
        self.identities = identities

    async def validate(self, token: str) -> ValidatedOidcIdentity:
        return self.identities[token]


def _oidc_identity(
    subject: str,
    *,
    organization: str = "dev-org",
    display_name: str = "OIDC Agent",
    email: str = "oidc-agent@example.test",
    groups: tuple[str, ...] = (),
) -> ValidatedOidcIdentity:
    return ValidatedOidcIdentity(
        "TEST_OIDC",
        "https://identity.example.test/issuer",
        subject,
        organization,
        display_name,
        email,
        "en-GB",
        groups,
    )


@contextmanager
def _oidc_client(
    identities: dict[str, ValidatedOidcIdentity],
    *,
    jit: bool = False,
    database_name: str = "identity_auth",
    rls_enabled: bool = False,
) -> Iterator[TestClient]:
    settings = _settings(database_name, rls_enabled=rls_enabled).model_copy(
        update={
            "developer_identity_enabled": False,
            "oidc_enabled": True,
            "oidc_provider_code": "TEST_OIDC",
            "oidc_issuer_url": "https://identity.example.test/issuer",
            "oidc_audience": "helpdesk-api",
            "oidc_jit_provisioning_enabled": jit,
        }
    )
    resources = _resources(settings)
    app = create_app(settings, resource_factory=lambda _: resources)
    database = cast(Database, resources.database)
    metrics = cast(AuthenticationMetrics, app.state.authentication_metrics)

    def unit_of_work_factory(context: RequestContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory, context, rls_enabled=rls_enabled)

    app.state.oidc_identity_service = OidcIdentityService(
        settings, StubOidcTokenValidator(identities), unit_of_work_factory, metrics
    )
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        yield client


@pytest.fixture
def identity_client() -> Iterator[TestClient]:
    settings = _settings("identity_auth")
    app = create_app(settings, resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        yield client


@pytest.mark.integration
def test_known_user_loads_database_roles_groups_and_business_unit(
    identity_client: TestClient,
) -> None:
    response = identity_client.get("/api/v1/me", headers={"X-Developer-User": "DEV/agent"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "22000000-0000-0000-0000-000000000004"
    assert payload["tenant_id"] == "20000000-0000-0000-0000-000000000001"
    assert payload["role_codes"] == ["AGENT"]
    assert payload["support_group_ids"] == [
        "23000000-0000-0000-0000-000000000001",
        "23000000-0000-0000-0000-000000000002",
    ]
    assert payload["business_unit_id"] == "21000000-0000-0000-0000-000000000001"


@pytest.mark.integration
def test_oidc_identity_uses_database_authority_and_synchronizes_only_profile_fields() -> None:
    identity = _oidc_identity(
        "oidc-agent",
        display_name="Synchronized Agent",
        email="synchronized@example.test",
        groups=("PLATFORM_ADMIN", "INVENTED_ROLE"),
    )
    with _oidc_client({"signed-agent-token": identity}) as client:
        response = client.get("/api/v1/me", headers={"Authorization": "Bearer signed-agent-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["authentication_mode"] == "oidc"
    assert payload["provider_code"] == "TEST_OIDC"
    assert payload["role_codes"] == ["AGENT"]
    assert payload["support_group_ids"] == [
        "23000000-0000-0000-0000-000000000001",
        "23000000-0000-0000-0000-000000000002",
    ]
    persisted = _psql(
        "identity_auth",
        "-Atqc",
        "SELECT display_name || '|' || email_address FROM identity.app_user "
        "WHERE user_id = '22000000-0000-0000-0000-000000000004'",
    )
    assert persisted == "Synchronized Agent|synchronized@example.test"


@pytest.mark.integration
def test_unknown_oidc_identity_fails_closed_when_jit_is_disabled() -> None:
    with _oidc_client({"unknown-token": _oidc_identity("unknown-subject")}) as client:
        response = client.get("/api/v1/me", headers={"Authorization": "Bearer unknown-token"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'


@pytest.mark.integration
def test_jit_creates_minimal_user_without_roles_and_never_persists_bearer_token() -> None:
    raw_token = "raw-sensitive-jit-token"
    identity = _oidc_identity(
        "new-jit-subject",
        display_name="New JIT User",
        email="new-jit@example.test",
        groups=("PLATFORM_ADMIN",),
    )
    with _oidc_client({raw_token: identity}, jit=True) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert response.status_code == 200
    assert response.json()["role_codes"] == []
    assert response.json()["support_group_ids"] == []
    persisted = _psql(
        "identity_auth",
        "-Atqc",
        "SELECT count(*) || '|' || coalesce(string_agg(ur.role_code, ','), '') "
        "FROM identity.external_identity ei "
        "JOIN identity.app_user u ON u.user_id = ei.user_id AND u.tenant_id = ei.tenant_id "
        "LEFT JOIN identity.user_role ur ON ur.user_id = u.user_id AND ur.tenant_id = u.tenant_id "
        "WHERE ei.external_subject = 'new-jit-subject'",
    )
    assert persisted == "1|"
    audit_data = _psql(
        "identity_auth",
        "-Atqc",
        "SELECT coalesce(string_agg(event_data_json::text, ''), '') "
        "FROM audit.security_event WHERE event_data_json->>'authentication_mode' = 'oidc'",
    )
    assert raw_token not in audit_data


@pytest.mark.integration
@pytest.mark.anyio
async def test_concurrent_oidc_mappings_do_not_leak_tenants() -> None:
    identities = {
        "dev-token": _oidc_identity("oidc-agent"),
        "other-token": _oidc_identity(
            "oidc-other",
            organization="other-org",
            display_name="Other OIDC User",
            email="other@example.test",
        ),
    }
    settings = _settings("identity_auth").model_copy(
        update={
            "developer_identity_enabled": False,
            "oidc_enabled": True,
            "oidc_provider_code": "TEST_OIDC",
            "oidc_issuer_url": "https://identity.example.test/issuer",
            "oidc_audience": "helpdesk-api",
        }
    )
    resources = _resources(settings)
    app = create_app(settings, resource_factory=lambda _: resources)
    database = cast(Database, resources.database)
    metrics = cast(AuthenticationMetrics, app.state.authentication_metrics)

    def unit_of_work_factory(context: RequestContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory, context, rls_enabled=False)

    app.state.oidc_identity_service = OidcIdentityService(
        settings, StubOidcTokenValidator(identities), unit_of_work_factory, metrics
    )
    transport = httpx.ASGITransport(app=app)
    tokens = ["dev-token", "other-token"] * 5
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *(
                client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
                for token in tokens
            )
        )
    await resources.close()
    expected = [
        "20000000-0000-0000-0000-000000000001"
        if token == "dev-token"
        else "20000000-0000-0000-0000-000000000002"
        for token in tokens
    ]
    assert [response.json()["tenant_id"] for response in responses] == expected


@pytest.mark.integration
@pytest.mark.parametrize(
    "selector", ["DEV/unknown", "DEV/inactive-user", "INACTIVE/customer", "invalid"]
)
def test_invalid_and_inactive_users_fail_authentication(
    identity_client: TestClient, selector: str
) -> None:
    response = identity_client.get("/api/v1/me", headers={"X-Developer-User": selector})
    assert response.status_code == 401
    assert response.json()["correlation_id"] == response.headers["x-correlation-id"]
    assert "database" not in response.text.lower()


@pytest.mark.integration
def test_sensitive_selector_is_not_persisted(identity_client: TestClient) -> None:
    selector = "DEV/private-selector"
    response = identity_client.get("/api/v1/me", headers={"X-Developer-User": selector})
    assert response.status_code == 401
    persisted = _psql(
        "identity_auth",
        "-Atqc",
        "SELECT event_data_json::text FROM audit.security_event "
        "ORDER BY security_event_id DESC LIMIT 1",
    )
    assert selector not in persisted


@pytest.mark.integration
def test_disabled_developer_identity_attempt_is_audited() -> None:
    settings = _settings("identity_auth").model_copy(update={"developer_identity_enabled": False})
    app = create_app(settings, resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        response = client.get("/api/v1/me", headers={"X-Developer-User": "DEV/customer"})
    assert response.status_code == 401
    latest = _psql(
        "identity_auth",
        "-Atqc",
        "SELECT event_type FROM audit.security_event ORDER BY security_event_id DESC LIMIT 1",
    )
    assert latest == "DEVELOPER_IDENTITY_DISABLED_ATTEMPT"


@pytest.mark.integration
def test_inactive_role_definitions_are_ignored(identity_client: TestClient) -> None:
    _psql(
        "identity_auth",
        "-c",
        "UPDATE identity.role_definition SET active_flag = false WHERE role_code = 'AUDITOR'",
    )
    try:
        response = identity_client.get("/api/v1/me", headers={"X-Developer-User": "DEV/auditor"})
        assert response.status_code == 200
        assert response.json()["role_codes"] == []
    finally:
        _psql(
            "identity_auth",
            "-c",
            "UPDATE identity.role_definition SET active_flag = true WHERE role_code = 'AUDITOR'",
        )


@pytest.mark.integration
def test_tenant_isolation_and_authorization_security_events(identity_client: TestClient) -> None:
    dev = identity_client.get("/api/v1/me", headers={"X-Developer-User": "DEV/customer"})
    other = identity_client.get("/api/v1/me", headers={"X-Developer-User": "OTHER/customer"})
    denied = identity_client.get(
        "/api/v1/identity/diagnostics",
        headers={"X-Developer-User": "DEV/customer"},
    )
    allowed = identity_client.get(
        "/api/v1/identity/diagnostics",
        headers={"X-Developer-User": "DEV/platform-admin"},
    )
    assert dev.json()["tenant_id"] != other.json()["tenant_id"]
    assert denied.status_code == 403
    assert allowed.status_code == 200
    events = _psql(
        "identity_auth",
        "-Atqc",
        "SELECT string_agg(event_type, ',' ORDER BY security_event_id) "
        "FROM audit.security_event WHERE event_type IN "
        "('DEVELOPER_AUTHENTICATION_SUCCEEDED','AUTHORIZATION_DENIED',"
        "'PRIVILEGED_ENDPOINT_ACCESSED')",
    )
    assert "DEVELOPER_AUTHENTICATION_SUCCEEDED" in events
    assert "AUTHORIZATION_DENIED" in events
    assert "PRIVILEGED_ENDPOINT_ACCESSED" in events


@pytest.mark.integration
@pytest.mark.anyio
async def test_concurrent_identity_requests_do_not_leak() -> None:
    settings = _settings("identity_auth")
    app = create_app(settings, resource_factory=_resources)
    transport = httpx.ASGITransport(app=app)
    correlation_ids = [str(uuid4()) for _ in range(12)]
    selectors = ["DEV/customer", "OTHER/customer"] * 6
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *(
                client.get(
                    "/api/v1/me",
                    headers={
                        "X-Developer-User": selector,
                        "X-Correlation-ID": correlation_id,
                    },
                )
                for selector, correlation_id in zip(selectors, correlation_ids, strict=True)
            )
        )
    await app.state.resources.close()
    expected_tenants = [
        "20000000-0000-0000-0000-000000000001"
        if selector.startswith("DEV/")
        else "20000000-0000-0000-0000-000000000002"
        for selector in selectors
    ]
    assert [response.json()["tenant_id"] for response in responses] == expected_tenants
    assert [
        response.json()["correlation_id"]
        if "correlation_id" in response.json()
        else response.headers["x-correlation-id"]
        for response in responses
    ] == correlation_ids


def _context(tenant_id: str, user_id: str) -> RequestContext:
    return RequestContext(
        UUID(tenant_id),
        UUID(user_id),
        "integration-subject",
        frozenset(),
        frozenset(),
        None,
        str(uuid4()),
        str(uuid4()),
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_transaction_context_and_optional_rls_fail_closed_for_non_owner() -> None:
    engine = create_async_engine(_app_url("identity_rls"), pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    dev_context = _context(
        "20000000-0000-0000-0000-000000000001",
        "22000000-0000-0000-0000-000000000005",
    )
    try:
        async with sessions() as session, session.begin():
            await apply_transaction_context(session, dev_context, rls_enabled=True)
            visible = await session.scalar(text("SELECT count(*) FROM identity.app_user"))
            assert visible == 10
            assert await session.scalar(text("SELECT current_setting('app.user_id')")) == str(
                dev_context.user_id
            )
        async with sessions() as session, session.begin():
            leaked_tenant = await session.scalar(
                text("SELECT NULLIF(current_setting('app.tenant_id', true), '')")
            )
            leaked_user = await session.scalar(
                text("SELECT NULLIF(current_setting('app.user_id', true), '')")
            )
            visible_without_context = await session.scalar(
                text("SELECT count(*) FROM identity.app_user")
            )
            assert leaked_tenant is None
            assert leaked_user is None
            assert visible_without_context == 0
        other_context = _context(
            "20000000-0000-0000-0000-000000000099",
            "22000000-0000-0000-0000-000000000099",
        )
        async with sessions() as session, session.begin():
            await apply_transaction_context(session, other_context, rls_enabled=True)
            assert await session.scalar(text("SELECT count(*) FROM identity.app_user")) == 0

        async def concurrent_visibility(context: RequestContext) -> tuple[str, str, int]:
            async with sessions() as session, session.begin():
                await apply_transaction_context(session, context, rls_enabled=True)
                await asyncio.sleep(0)
                tenant = await session.scalar(text("SELECT current_setting('app.tenant_id')"))
                user = await session.scalar(text("SELECT current_setting('app.user_id')"))
                count = await session.scalar(text("SELECT count(*) FROM identity.app_user"))
                assert tenant is not None and user is not None and count is not None
                return tenant, user, count

        dev_result, other_result = await asyncio.gather(
            concurrent_visibility(dev_context), concurrent_visibility(other_context)
        )
        assert dev_result == (str(dev_context.tenant_id), str(dev_context.user_id), 10)
        assert other_result == (str(other_context.tenant_id), str(other_context.user_id), 0)
    finally:
        await engine.dispose()

    owner = create_async_engine(_admin_url("identity_rls"))
    try:
        async with owner.connect() as connection:
            owner_visible = await connection.scalar(text("SELECT count(*) FROM identity.app_user"))
        assert owner_visible == 10
    finally:
        await owner.dispose()


@pytest.mark.integration
def test_developer_authentication_operates_with_optional_rls() -> None:
    settings = _settings("identity_rls", rls_enabled=True)
    app = create_app(settings, resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        response = client.get("/api/v1/me", headers={"X-Developer-User": "DEV/agent"})
    assert response.status_code == 200
    assert response.json()["role_codes"] == ["AGENT"]


@pytest.mark.integration
def test_oidc_authentication_operates_with_optional_rls() -> None:
    with _oidc_client(
        {"rls-token": _oidc_identity("oidc-agent")},
        database_name="identity_rls",
        rls_enabled=True,
    ) as client:
        response = client.get("/api/v1/me", headers={"Authorization": "Bearer rls-token"})
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "20000000-0000-0000-0000-000000000001"
    assert response.json()["role_codes"] == ["AGENT"]


def test_development_seed_is_not_in_the_production_baseline_installer() -> None:
    installer = (ROOT / "database/baseline/fusion_helpdesk_postgres/sql/install_all.sql").read_text(
        encoding="utf-8"
    )
    assert "identity_personas.sql" not in installer
    assert "20000000-0000-0000-0000-000000000001" not in installer
