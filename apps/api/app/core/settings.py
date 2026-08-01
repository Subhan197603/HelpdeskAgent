"""Typed application configuration with production safety checks."""

from enum import StrEnum
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    INTEGRATION = "integration"
    PREPRODUCTION = "preproduction"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Configuration sourced from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Fusion AI Helpdesk API"
    app_version: str = "0.1.0"
    app_env: Environment = Environment.DEVELOPMENT
    app_debug: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = False

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://helpdesk:helpdesk@localhost:5432/helpdesk"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: float = 30.0
    database_pool_recycle: int = 1800
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    object_storage_enabled: bool = True
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "helpdesk"
    object_storage_region: str = "us-east-1"
    object_storage_use_ssl: bool = False
    object_storage_access_key: SecretStr | None = None
    object_storage_secret_key: SecretStr | None = None

    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_required: bool = False
    log_level: str = "INFO"
    json_logs: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    cors_allowed_origins: list[str] = ["http://localhost:3000"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    rls_enabled: bool = False
    dev_identity_enabled: bool = False
    ai_globally_enabled: bool = False

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> Self:
        if self.api_reload and self.app_env not in {Environment.DEVELOPMENT, Environment.TEST}:
            raise ValueError("API reload is permitted only in development or test")
        if self.app_env is not Environment.PRODUCTION:
            return self

        errors: list[str] = []
        if self.app_debug:
            errors.append("APP_DEBUG must be false")
        if not self.json_logs:
            errors.append("JSON_LOGS must be true")
        if self.dev_identity_enabled:
            errors.append("DEV_IDENTITY_ENABLED must be false")
        if "*" in self.cors_allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS cannot contain '*'")
        if "*" in self.trusted_hosts:
            errors.append("TRUSTED_HOSTS cannot contain '*'")
        if not self.otel_exporter_otlp_endpoint:
            errors.append("OTEL_EXPORTER_OTLP_ENDPOINT is required")
        database_url = self.database_url.get_secret_value().lower()
        if "@localhost" in database_url or "helpdesk:helpdesk@" in database_url:
            errors.append("DATABASE_URL must be explicitly provisioned for production")
        if "localhost" in self.redis_url.get_secret_value().lower():
            errors.append("REDIS_URL must be explicitly provisioned for production")
        if self.object_storage_enabled:
            if "localhost" in self.object_storage_endpoint.lower():
                errors.append("OBJECT_STORAGE_ENDPOINT must be provisioned for production")
            if self.object_storage_access_key is None:
                errors.append("OBJECT_STORAGE_ACCESS_KEY is required")
            elif self.object_storage_access_key.get_secret_value().lower() in {
                "minio",
                "change-me",
            }:
                errors.append("OBJECT_STORAGE_ACCESS_KEY cannot use a development placeholder")
            if self.object_storage_secret_key is None:
                errors.append("OBJECT_STORAGE_SECRET_KEY is required")
            elif self.object_storage_secret_key.get_secret_value().lower() in {
                "minio",
                "change-me",
            }:
                errors.append("OBJECT_STORAGE_SECRET_KEY cannot use a development placeholder")
        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def debug(self) -> bool:
        return self.app_debug
