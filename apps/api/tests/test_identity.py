"""Developer authentication and authorization unit tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from apps.api.app.audit.security_events import SecurityEvent
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthenticationError
from apps.api.app.core.settings import Settings
from apps.api.app.identity.authorization import (
    AuthorizationResource,
    AuthorizationService,
    Permission,
)
from apps.api.app.identity.models import AuthenticatedIdentity
from apps.api.app.identity.oidc import OidcAuthenticationError, OidcFailureReason
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings


def identity(*, roles: frozenset[str] = frozenset({"CUSTOMER"})) -> AuthenticatedIdentity:
    context = RequestContext(
        tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
        user_id=UUID("22000000-0000-0000-0000-000000000005"),
        external_subject="customer",
        roles=roles,
        support_group_ids=frozenset(),
        business_unit_id=UUID("21000000-0000-0000-0000-000000000001"),
        correlation_id=str(uuid4()),
        request_id=str(uuid4()),
    )
    return AuthenticatedIdentity(context, "Development Customer", "Local Development")


class FakeDeveloperIdentityService:
    def __init__(self, resolved: AuthenticatedIdentity | None = None) -> None:
        self.resolved = resolved or identity()
        self.events: list[SecurityEvent] = []
        self.failure: AuthenticationError | None = None

    async def authenticate(
        self, selector: str, anonymous_context: RequestContext
    ) -> AuthenticatedIdentity:
        if self.failure is not None:
            raise self.failure
        context = self.resolved.context
        request_context = RequestContext(
            context.tenant_id,
            context.user_id,
            context.external_subject,
            context.roles,
            context.support_group_ids,
            context.business_unit_id,
            anonymous_context.correlation_id,
            anonymous_context.request_id,
        )
        return AuthenticatedIdentity(
            request_context,
            self.resolved.display_name,
            self.resolved.business_unit_name,
        )

    async def record_event(self, context: RequestContext, event: SecurityEvent) -> None:
        self.events.append(event)


class FakeOidcIdentityService:
    def __init__(self, resolved: AuthenticatedIdentity) -> None:
        self.resolved = resolved
        self.tokens: list[str] = []
        self.failure: AuthenticationError | None = None

    async def authenticate(
        self, token: str, anonymous_context: RequestContext
    ) -> AuthenticatedIdentity:
        self.tokens.append(token)
        if self.failure is not None:
            raise self.failure
        original = self.resolved.context
        context = RequestContext(
            original.tenant_id,
            original.user_id,
            original.external_subject,
            original.roles,
            original.support_group_ids,
            original.business_unit_id,
            anonymous_context.correlation_id,
            anonymous_context.request_id,
        )
        return AuthenticatedIdentity(
            context,
            self.resolved.display_name,
            self.resolved.business_unit_name,
            authentication_mode="oidc",
            provider_code="TEST_OIDC",
        )


@contextmanager
def identity_client(
    service: FakeDeveloperIdentityService, *, enabled: bool = True
) -> Iterator[TestClient]:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())
    app = create_app(
        make_test_settings(developer_identity_enabled=enabled),
        resource_factory=lambda _: resources,
    )
    app.state.developer_identity_service = service
    with TestClient(app) as client:
        yield client


@contextmanager
def oidc_client(
    oidc_service: FakeOidcIdentityService,
    developer_service: FakeDeveloperIdentityService | None = None,
) -> Iterator[TestClient]:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())
    app = create_app(
        make_test_settings(
            oidc_enabled=True,
            oidc_provider_code="TEST_OIDC",
            oidc_issuer_url="https://identity.example.test/issuer",
            oidc_audience="helpdesk-api",
            developer_identity_enabled=True,
        ),
        resource_factory=lambda _: resources,
    )
    app.state.oidc_identity_service = oidc_service
    app.state.developer_identity_service = developer_service or FakeDeveloperIdentityService()
    with TestClient(app) as client:
        yield client


def production_oidc_settings(*, diagnostics: bool) -> Settings:
    return make_test_settings(
        app_env="production",
        json_logs=True,
        otel_exporter_otlp_endpoint="https://telemetry.example.test",
        object_storage_enabled=False,
        database_url="postgresql+psycopg://api:secret@db.example.test/helpdesk",
        redis_url="rediss://cache.example.test/0",
        trusted_hosts=["testserver"],
        cors_allowed_origins=["https://helpdesk.example.test"],
        oidc_enabled=True,
        oidc_provider_code="TEST_OIDC",
        oidc_issuer_url="https://identity.example.test/issuer",
        oidc_audience="helpdesk-api",
        oidc_client_id="helpdesk-web",
        oidc_diagnostics_enabled=diagnostics,
        retrieval_embedding_provider="http",
        retrieval_embedding_endpoint="https://ai.example.test/embeddings",
        retrieval_embedding_api_key="retrieval-secret",
    )


def test_developer_identity_is_disabled_by_default() -> None:
    service = FakeDeveloperIdentityService()
    with identity_client(service, enabled=False) as client:
        response = client.get("/api/v1/me", headers={"X-Developer-User": "DEV/customer"})
    assert response.status_code == 401
    assert service.events[0].event_type == "DEVELOPER_IDENTITY_DISABLED_ATTEMPT"


def test_developer_identity_is_rejected_in_production() -> None:
    with pytest.raises(PydanticValidationError, match="DEVELOPER_IDENTITY_ENABLED"):
        make_test_settings(
            app_env="production",
            developer_identity_enabled=True,
            json_logs=True,
            otel_exporter_otlp_endpoint="https://telemetry.example.test",
            object_storage_access_key="access",
            object_storage_secret_key="secret",
            database_url="postgresql+psycopg://api:secret@db.example.test/helpdesk",
            redis_url="rediss://cache.example.test/0",
            object_storage_endpoint="https://objects.example.test",
            oidc_enabled=True,
            oidc_provider_code="ENTERPRISE_OIDC",
            oidc_issuer_url="https://identity.example.test/issuer",
            oidc_audience="helpdesk-api",
            oidc_client_id="helpdesk-web",
        )


def test_missing_unknown_and_inactive_identity_return_401_with_correlation_id() -> None:
    for failure in (None, "unknown", "inactive"):
        service = FakeDeveloperIdentityService()
        if failure is not None:
            service.failure = AuthenticationError("Developer identity is invalid.")
        with identity_client(service) as client:
            headers = {} if failure is None else {"X-Developer-User": f"DEV/{failure}"}
            response = client.get("/api/v1/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["correlation_id"] == response.headers["x-correlation-id"]


def test_sensitive_developer_selector_is_absent_from_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    selector = "DEV/sensitive-local-selector"
    service = FakeDeveloperIdentityService()
    service.failure = AuthenticationError("Developer identity is invalid.")
    with identity_client(service) as client:
        response = client.get("/api/v1/me", headers={"X-Developer-User": selector})
    assert response.status_code == 401
    assert selector not in caplog.text
    assert selector not in response.text


def test_me_returns_only_authenticated_profile_fields() -> None:
    service = FakeDeveloperIdentityService()
    with identity_client(service) as client:
        response = client.get("/api/v1/me", headers={"X-Developer-User": "DEV/customer"})
    assert response.status_code == 200
    assert response.json()["role_codes"] == ["CUSTOMER"]
    assert "TICKET_READ_OWN" in response.json()["permission_codes"]
    assert "TICKET_ANALYST_READ" not in response.json()["permission_codes"]
    assert response.json()["display_name"] == "Development Customer"
    assert response.json()["authentication_mode"] == "developer_header"
    assert "email" not in response.text


def test_oidc_mode_uses_bearer_identity_and_reports_provider() -> None:
    service = FakeOidcIdentityService(identity())
    with oidc_client(service) as client:
        response = client.get("/api/v1/me", headers={"Authorization": "Bearer signed-token"})
    assert response.status_code == 200
    assert response.json()["authentication_mode"] == "oidc"
    assert response.json()["provider_code"] == "TEST_OIDC"
    assert service.tokens == ["signed-token"]


def test_invalid_bearer_never_falls_back_to_developer_identity() -> None:
    oidc_service = FakeOidcIdentityService(identity())
    oidc_service.failure = OidcAuthenticationError(OidcFailureReason.INVALID_SIGNATURE)
    developer_service = FakeDeveloperIdentityService()
    with oidc_client(oidc_service, developer_service) as client:
        response = client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert developer_service.events == []


def test_multiple_authentication_mechanisms_are_rejected_before_resolution() -> None:
    oidc_service = FakeOidcIdentityService(identity())
    developer_service = FakeDeveloperIdentityService()
    with oidc_client(oidc_service, developer_service) as client:
        response = client.get(
            "/api/v1/me",
            headers={
                "Authorization": "Bearer signed-token",
                "X-Developer-User": "DEV/customer",
            },
        )
    assert response.status_code == 401
    assert oidc_service.tokens == []
    assert developer_service.events[0].event_type == "MULTIPLE_AUTHENTICATION_MECHANISMS"


@pytest.mark.parametrize("authorization", ["Basic value", "Bearer", "Bearer too many"])
def test_malformed_authorization_header_is_controlled(authorization: str) -> None:
    service = FakeOidcIdentityService(identity())
    with oidc_client(service) as client:
        response = client.get("/api/v1/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert service.tokens == []


@pytest.mark.parametrize("header", ["X-Tenant-ID", "X-Roles", "X-Permissions"])
def test_caller_cannot_inject_authorization_context(header: str) -> None:
    service = FakeDeveloperIdentityService()
    with identity_client(service) as client:
        response = client.get(
            "/api/v1/me",
            headers={"X-Developer-User": "DEV/customer", header: "PLATFORM_ADMIN"},
        )
    assert response.status_code == 401
    assert service.events[0].event_type == "DEVELOPER_IDENTITY_CONTEXT_INJECTION_ATTEMPT"


def test_policy_denies_unknown_roles_and_cross_tenant_resources() -> None:
    service = AuthorizationService()
    unknown = identity(roles=frozenset({"INVENTED_ADMIN"})).context
    assert not service.is_allowed(unknown, Permission.ADMIN_IDENTITY_READ)
    assert not service.is_allowed(unknown, Permission.CATALOG_PROJECT_LIST)
    assert not service.is_allowed(
        unknown,
        Permission.IDENTITY_SELF_READ,
        AuthorizationResource(tenant_id=uuid4()),
    )


def test_admin_diagnostic_returns_403_and_audits_denial_for_customer() -> None:
    service = FakeDeveloperIdentityService()
    with identity_client(service) as client:
        response = client.get(
            "/api/v1/identity/diagnostics",
            headers={"X-Developer-User": "DEV/customer"},
        )
    assert response.status_code == 403
    assert service.events[-1].event_type == "AUTHORIZATION_DENIED"


def test_admin_diagnostic_allows_platform_admin_and_audits_access() -> None:
    service = FakeDeveloperIdentityService(identity(roles=frozenset({"PLATFORM_ADMIN"})))
    with identity_client(service) as client:
        response = client.get(
            "/api/v1/identity/diagnostics",
            headers={"X-Developer-User": "DEV/platform-admin"},
        )
    assert response.status_code == 200
    assert service.events[-1].event_type == "PRIVILEGED_ENDPOINT_ACCESSED"


def test_production_diagnostic_is_absent_until_explicitly_enabled() -> None:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())
    app = create_app(
        production_oidc_settings(diagnostics=False), resource_factory=lambda _: resources
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/identity/diagnostics")
    assert response.status_code == 404


def test_enabled_production_diagnostic_remains_admin_only_and_sanitized() -> None:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())
    app = create_app(
        production_oidc_settings(diagnostics=True), resource_factory=lambda _: resources
    )
    app.state.oidc_identity_service = FakeOidcIdentityService(
        identity(roles=frozenset({"PLATFORM_ADMIN"}))
    )
    app.state.developer_identity_service = FakeDeveloperIdentityService()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/identity/diagnostics", headers={"Authorization": "Bearer signed-token"}
        )
    assert response.status_code == 200
    assert response.json()["issuer_configured"] is True
    assert response.json()["audience_configured"] is True
    assert "issuer_url" not in response.text
    assert "client_id" not in response.text


def test_health_remains_anonymous_when_developer_header_is_present() -> None:
    service = FakeDeveloperIdentityService()
    with identity_client(service) as client:
        response = client.get("/health/live", headers={"X-Developer-User": "DEV/customer"})
    assert response.status_code == 200
    assert service.events == []
