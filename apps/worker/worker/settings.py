"""Typed settings for the non-owner background worker runtime."""

import socket
from typing import Literal, Self

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
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "helpdesk"
    object_storage_region: str = "us-east-1"
    object_storage_use_ssl: bool = False
    object_storage_access_key: SecretStr | None = None
    object_storage_secret_key: SecretStr | None = None
    object_storage_server_side_encryption: Literal["AES256", "aws:kms"] | None = None
    object_storage_sse_key_id: SecretStr | None = None
    knowledge_document_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    acquisition_fetch_timeout_seconds: float = Field(default=30, ge=1, le=120)
    clamav_host: str = "localhost"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=15, gt=0, le=120)
    oracle_document_acquisition_enabled: bool = False
    smtp_host: str = Field(default="localhost", min_length=1, max_length=253)
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_from: str = Field(default="helpdesk@example.invalid", min_length=3, max_length=320)
    smtp_username: str | None = Field(default=None, max_length=320)
    smtp_password: SecretStr = Field(default=SecretStr(""))
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = Field(default=10, ge=1, le=60)
    smtp_message_id_domain: str = Field(default="helpdesk.local", min_length=1, max_length=253)
    log_level: str = "INFO"
    json_logs: bool = False

    @model_validator(mode="after")
    def validate_production_database(self) -> Self:
        if bool(self.smtp_username) != bool(self.smtp_password.get_secret_value()):
            raise ValueError("SMTP username and password must be configured together")
        if self.app_env is not Environment.PRODUCTION:
            return self
        value = self.worker_database_url.get_secret_value().lower()
        if "@localhost" in value or ":helpdesk@" in value:
            raise ValueError("WORKER_DATABASE_URL must be explicitly provisioned for production")
        if not self.json_logs:
            raise ValueError("JSON_LOGS must be true in production")
        if self.smtp_host.lower() in {"localhost", "mailpit"}:
            raise ValueError("SMTP_HOST must be explicitly provisioned for production")
        if not self.smtp_starttls:
            raise ValueError("SMTP_STARTTLS must be true in production")
        storage_credentials = (
            self.object_storage_access_key.get_secret_value().lower()
            if self.object_storage_access_key
            else ""
        )
        storage_secret = (
            self.object_storage_secret_key.get_secret_value().lower()
            if self.object_storage_secret_key
            else ""
        )
        if storage_credentials in {"", "minio", "change-me"} or storage_secret in {
            "",
            "minio",
            "change-me",
        }:
            raise ValueError("Object storage credentials must be configured in production")
        if self.object_storage_server_side_encryption is None:
            raise ValueError("Object storage encryption must be configured in production")
        if (
            self.object_storage_server_side_encryption == "aws:kms"
            and self.object_storage_sse_key_id is None
        ):
            raise ValueError("OBJECT_STORAGE_SSE_KEY_ID is required for aws:kms")
        return self
