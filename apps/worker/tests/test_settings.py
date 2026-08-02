"""Worker configuration safety tests."""

import pytest
from pydantic import ValidationError

from apps.worker.worker.settings import WorkerSettings


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
