"""Worker configuration safety tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.worker.worker.settings import WorkerSettings

EXAMPLE_ENV = Path(__file__).resolve().parents[3] / ".env.example"


def test_example_environment_loads_for_local_development() -> None:
    settings = WorkerSettings(_env_file=EXAMPLE_ENV)  # type: ignore[call-arg]

    assert settings.object_storage_server_side_encryption is None
    assert settings.object_storage_sse_key_id is None


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://worker:strong-password@localhost/helpdesk",
        "postgresql+psycopg://helpdesk_worker_login:helpdesk@postgres/helpdesk",
    ],
)
def test_production_rejects_local_worker_database_settings(database_url: str) -> None:
    with pytest.raises(ValidationError, match="explicitly provisioned"):
        WorkerSettings.model_validate(
            {
                "app_env": "production",
                "json_logs": True,
                "worker_database_url": database_url,
            }
        )


def test_production_requires_json_logging() -> None:
    with pytest.raises(ValidationError, match="JSON_LOGS"):
        WorkerSettings.model_validate(
            {
                "app_env": "production",
                "worker_database_url": (
                    "postgresql+psycopg://worker:strong-password@database.internal/helpdesk"
                ),
            }
        )


def test_smtp_credentials_must_be_configured_together() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        WorkerSettings.model_validate({"smtp_username": "mailer"})


@pytest.mark.parametrize(
    ("smtp_host", "starttls", "message"),
    [
        ("mailpit", True, "explicitly provisioned"),
        ("smtp.example.invalid", False, "SMTP_STARTTLS"),
    ],
)
def test_production_requires_remote_tls_smtp(smtp_host: str, starttls: bool, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        WorkerSettings.model_validate(
            {
                "app_env": "production",
                "json_logs": True,
                "worker_database_url": (
                    "postgresql+psycopg://worker:strong-password@database.internal/helpdesk"
                ),
                "smtp_host": smtp_host,
                "smtp_starttls": starttls,
            }
        )


def test_production_requires_encrypted_object_storage_credentials() -> None:
    common = {
        "app_env": "production",
        "json_logs": True,
        "worker_database_url": (
            "postgresql+psycopg://worker:strong-password@database.internal/helpdesk"
        ),
        "smtp_host": "smtp.example.invalid",
        "smtp_starttls": True,
    }
    with pytest.raises(ValidationError, match="credentials"):
        WorkerSettings.model_validate(common)
    with pytest.raises(ValidationError, match="encryption"):
        WorkerSettings.model_validate(
            common | {"object_storage_access_key": "access", "object_storage_secret_key": "secret"}
        )
