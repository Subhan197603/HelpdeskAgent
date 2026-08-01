"""Typed application configuration with production safety checks."""

from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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
    migration_database_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("MIGRATION_DATABASE_URL", "DATABASE_ADMIN_URL"),
    )
    migration_lock_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: float = 30.0
    database_pool_recycle: int = 1800
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    oidc_enabled: bool = False
    oidc_provider_code: str | None = None
    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_allowed_algorithms: list[str] = ["RS256"]
    oidc_discovery_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    oidc_jwks_cache_seconds: int = Field(default=3600, ge=60, le=86400)
    oidc_jwks_stale_if_error_seconds: int = Field(default=300, ge=0, le=3600)
    oidc_clock_skew_seconds: int = Field(default=60, ge=0, le=300)
    oidc_jit_provisioning_enabled: bool = False
    oidc_profile_synchronization_enabled: bool = True
    oidc_group_synchronization_enabled: bool = False
    oidc_required_claims: list[str] = ["sub", "exp"]
    oidc_claim_mappings: dict[str, str] = {
        "display_name": "name",
        "email": "email",
        "locale": "locale",
        "groups": "groups",
    }
    oidc_organization_claim: str | None = None
    oidc_authorized_party: str | None = None
    oidc_required_token_type: str | None = None
    oidc_diagnostics_enabled: bool = False

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
    developer_identity_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEVELOPER_IDENTITY_ENABLED", "DEV_IDENTITY_ENABLED"),
    )
    developer_identity_header: str = "X-Developer-User"
    ai_globally_enabled: bool = False

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> Self:
        if self.api_reload and self.app_env not in {Environment.DEVELOPMENT, Environment.TEST}:
            raise ValueError("API reload is permitted only in development or test")
        oidc_errors: list[str] = []
        if self.oidc_enabled:
            if not self.oidc_provider_code:
                oidc_errors.append("OIDC_PROVIDER_CODE is required")
            if not self.oidc_issuer_url:
                oidc_errors.append("OIDC_ISSUER_URL is required")
            if not self.oidc_audience:
                oidc_errors.append("OIDC_AUDIENCE is required")
        if oidc_errors:
            raise ValueError("Invalid OIDC configuration: " + "; ".join(oidc_errors))

        if self.app_env is not Environment.PRODUCTION:
            return self

        errors: list[str] = []
        if not self.oidc_enabled:
            errors.append("OIDC_ENABLED must be true")
        if not self.oidc_client_id:
            errors.append("OIDC_CLIENT_ID is required")
        if self.oidc_issuer_url and urlsplit(self.oidc_issuer_url).scheme != "https":
            errors.append("OIDC_ISSUER_URL must use HTTPS")
        if self.app_debug:
            errors.append("APP_DEBUG must be false")
        if not self.json_logs:
            errors.append("JSON_LOGS must be true")
        if self.developer_identity_enabled:
            errors.append("DEVELOPER_IDENTITY_ENABLED must be false")
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

    @field_validator("developer_identity_header")
    @classmethod
    def validate_developer_identity_header(cls, value: str) -> str:
        forbidden = {
            "x-tenant-id",
            "x-user-id",
            "x-roles",
            "x-permissions",
            "x-support-group-ids",
            "x-business-unit-id",
        }
        normalized = value.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("DEVELOPER_IDENTITY_HEADER must be a non-empty header name")
        if normalized.lower() in forbidden:
            raise ValueError("DEVELOPER_IDENTITY_HEADER cannot be an authorization-data header")
        if not all(character.isalnum() or character == "-" for character in normalized):
            raise ValueError("DEVELOPER_IDENTITY_HEADER is not a valid HTTP header name")
        return normalized

    @field_validator("oidc_provider_code")
    @classmethod
    def validate_oidc_provider_code(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().upper()
        if (
            not normalized
            or len(normalized) > 80
            or not all(character.isalnum() or character in {"_", "-"} for character in normalized)
        ):
            raise ValueError("OIDC_PROVIDER_CODE must be a stable code")
        return normalized

    @field_validator("oidc_issuer_url")
    @classmethod
    def validate_oidc_issuer_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "OIDC_ISSUER_URL must be an absolute issuer URL without query or fragment"
            )
        return normalized

    @field_validator("oidc_allowed_algorithms")
    @classmethod
    def validate_oidc_algorithms(cls, value: list[str]) -> list[str]:
        safe_algorithms = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
        normalized = list(dict.fromkeys(value))
        if not normalized or any(item not in safe_algorithms for item in normalized):
            raise ValueError("OIDC_ALLOWED_ALGORITHMS must contain supported asymmetric algorithms")
        return normalized

    @field_validator("oidc_required_claims")
    @classmethod
    def validate_oidc_required_claims(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        for required in ("sub", "exp"):
            if required not in normalized:
                normalized.append(required)
        return normalized

    @field_validator("oidc_claim_mappings")
    @classmethod
    def validate_oidc_claim_mappings(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"display_name", "email", "locale", "groups"}
        if set(value) - allowed or any(not claim.strip() for claim in value.values()):
            raise ValueError("OIDC_CLAIM_MAPPINGS contains an unsupported or empty mapping")
        return {key: claim.strip() for key, claim in value.items()}

    @property
    def dev_identity_enabled(self) -> bool:
        """Compatibility alias for the Task 1.1 setting name."""
        return self.developer_identity_enabled
