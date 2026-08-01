"""Settings validation and secret-handling tests."""

import json
import logging

import pytest
from pydantic import ValidationError as PydanticValidationError

from apps.api.app.core.logging import configure_logging
from apps.api.app.core.settings import Settings

from .conftest import make_test_settings


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(PydanticValidationError, match="app_env"):
        make_test_settings(app_env="somewhere")


def test_production_requires_secure_configuration() -> None:
    with pytest.raises(PydanticValidationError, match="Unsafe production configuration"):
        make_test_settings(
            app_env="production",
            app_debug=True,
            json_logs=False,
            trusted_hosts=["*"],
            cors_allowed_origins=["*"],
        )


def test_production_accepts_explicit_secure_configuration() -> None:
    settings = make_test_settings(
        app_env="production",
        json_logs=True,
        otel_exporter_otlp_endpoint="https://telemetry.example.test",
        object_storage_access_key="access",
        object_storage_secret_key="secret",
        database_url="postgresql+psycopg://api_user:secret@db.example.test/helpdesk",
        redis_url="rediss://cache.example.test/0",
        object_storage_endpoint="https://objects.example.test",
        trusted_hosts=["api.example.test"],
        cors_allowed_origins=["https://helpdesk.example.test"],
        oidc_enabled=True,
        oidc_provider_code="ENTERPRISE_OIDC",
        oidc_issuer_url="https://identity.example.test/issuer",
        oidc_audience="helpdesk-api",
        oidc_client_id="helpdesk-web",
    )
    assert settings.is_production


def test_oidc_requires_complete_configuration_and_asymmetric_algorithms() -> None:
    with pytest.raises(PydanticValidationError, match="OIDC_PROVIDER_CODE"):
        make_test_settings(oidc_enabled=True)
    with pytest.raises(PydanticValidationError, match="asymmetric algorithms"):
        make_test_settings(oidc_allowed_algorithms=["HS256"])


def test_production_requires_oidc_and_https_issuer() -> None:
    common: dict[str, object] = {
        "app_env": "production",
        "json_logs": True,
        "otel_exporter_otlp_endpoint": "https://telemetry.example.test",
        "object_storage_enabled": False,
        "database_url": "postgresql+psycopg://api:secret@db.example.test/helpdesk",
        "redis_url": "rediss://cache.example.test/0",
        "trusted_hosts": ["api.example.test"],
    }
    with pytest.raises(PydanticValidationError, match="OIDC_ENABLED"):
        make_test_settings(**common)
    with pytest.raises(PydanticValidationError, match="must use HTTPS"):
        make_test_settings(
            **common,
            oidc_enabled=True,
            oidc_provider_code="ENTERPRISE_OIDC",
            oidc_issuer_url="http://identity.example.test/issuer",
            oidc_audience="helpdesk-api",
            oidc_client_id="helpdesk-web",
        )


def test_secret_settings_are_redacted() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://user:super-secret@db/helpdesk",
            "redis_url": "redis://:redis-secret@redis/0",
        }
    )
    rendered = repr(settings)
    assert "super-secret" not in rendered
    assert "redis-secret" not in rendered


def test_json_logging_is_structured_redacted_and_not_duplicated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = make_test_settings(
        json_logs=True,
        database_url="postgresql+psycopg://user:super-secret@localhost/helpdesk",
    )
    configure_logging(settings)
    configure_logging(settings)
    owned_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_fusion_helpdesk", False)
    ]
    assert len(owned_handlers) == 1

    logging.getLogger("test.safe_logging").warning("Configuration loaded")
    output = capsys.readouterr().err.strip()
    payload = json.loads(output)
    assert payload["msg"] == "Configuration loaded"
    assert payload["env"] == "test"
    assert payload["trace_id"] is None
    assert "super-secret" not in output
