"""Public authentication-configuration endpoint tests (DEF-RC1-001)."""

from fastapi.testclient import TestClient

from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings

PATH = "/api/v1/auth/configuration"


def _client(**overrides: object) -> TestClient:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())
    app = create_app(make_test_settings(**overrides), resource_factory=lambda _: resources)
    return TestClient(app)


def test_endpoint_is_public_and_reports_developer_mode(client: TestClient) -> None:
    response = client.get(PATH)
    assert response.status_code == 200
    payload = response.json()
    assert payload["oidc_enabled"] is False
    assert payload["developer_identity_enabled"] is False
    assert payload["issuer_url"] is None
    assert payload["client_id"] is None


def test_reports_oidc_configuration_without_secrets() -> None:
    with _client(
        oidc_enabled=True,
        oidc_provider_code="TEST_OIDC",
        oidc_issuer_url="https://identity.example.test/issuer",
        oidc_client_id="confidential-client",
        oidc_client_secret="super-secret-value",
        oidc_audience="helpdesk-api",
        oidc_redirect_uri="https://helpdesk.example.test/auth/callback",
    ) as client:
        payload = client.get(PATH).json()
    assert payload["oidc_enabled"] is True
    assert payload["issuer_url"] == "https://identity.example.test/issuer"
    assert payload["client_id"] == "confidential-client"
    assert payload["audience"] == "helpdesk-api"
    assert payload["redirect_uri"] == "https://helpdesk.example.test/auth/callback"
    assert payload["scopes"] == "openid profile email"
    assert "super-secret-value" not in str(payload)
    assert "client_secret" not in payload


def test_public_client_id_overrides_confidential_client_id() -> None:
    with _client(
        oidc_enabled=True,
        oidc_provider_code="TEST_OIDC",
        oidc_issuer_url="https://identity.example.test/issuer",
        oidc_client_id="confidential-client",
        oidc_public_client_id="spa-public-client",
        oidc_audience="helpdesk-api",
        oidc_scopes="openid profile",
    ) as client:
        payload = client.get(PATH).json()
    assert payload["client_id"] == "spa-public-client"
    assert payload["scopes"] == "openid profile"


def test_developer_identity_reported_only_when_enabled() -> None:
    with _client(developer_identity_enabled=True) as client:
        assert client.get(PATH).json()["developer_identity_enabled"] is True
