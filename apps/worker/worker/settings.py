"""Typed settings for the non-owner background worker runtime."""

import socket
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.api.app.core.settings import Environment


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Environment = Environment.DEVELOPMENT
    worker_database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+psycopg://helpdesk_worker_login:helpdesk@localhost:5432/helpdesk"
        ),
    )
    worker_id: str = Field(default_factory=socket.gethostname, min_length=1, max_length=200)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    worker_due_scan_seconds: float = Field(default=15.0, ge=1, le=300)
    worker_batch_size: int = Field(default=50, ge=1, le=500)
    worker_max_attempts: int = Field(default=5, ge=1, le=20)
    log_level: str = "INFO"
    json_logs: bool = False

    @model_validator(mode="after")
    def validate_production_database(self) -> Self:
        if self.app_env is not Environment.PRODUCTION:
            return self
        value = self.worker_database_url.get_secret_value().lower()
        if "@localhost" in value or ":helpdesk@" in value:
            raise ValueError("WORKER_DATABASE_URL must be explicitly provisioned for production")
        if not self.json_logs:
            raise ValueError("JSON_LOGS must be true in production")
        return self
