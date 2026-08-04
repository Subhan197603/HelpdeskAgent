"""Typed application configuration with production safety checks."""

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
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
    oidc_public_client_id: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_scopes: str = "openid profile email"
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
    object_storage_server_side_encryption: Literal["AES256", "aws:kms"] | None = None
    object_storage_sse_key_id: SecretStr | None = None
    attachment_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    attachment_upload_url_seconds: int = Field(default=900, ge=60, le=3600)
    attachment_download_url_seconds: int = Field(default=300, ge=30, le=900)
    knowledge_document_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    knowledge_upload_url_seconds: int = Field(default=900, ge=60, le=3600)
    acquisition_fetch_timeout_seconds: float = Field(default=30, ge=1, le=120)

    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_required: bool = False
    clamav_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    clamav_max_attempts: int = Field(default=3, ge=1, le=10)
    clamav_retry_seconds: int = Field(default=30, ge=1, le=3600)
    log_level: str = "INFO"
    json_logs: bool = False
    metrics_endpoint_enabled: bool = True
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
    ai_provider_timeout_seconds: float = Field(default=30, ge=1, le=120)
    ai_provider_max_attempts: int = Field(default=3, ge=1, le=5)
    ai_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    ai_circuit_recovery_seconds: float = Field(default=60, ge=1, le=3600)
    openai_api_endpoint: str = "https://api.openai.com/v1/responses"
    openai_api_key: SecretStr | None = None
    openai_model_aliases: dict[str, str] = Field(default_factory=dict)
    anthropic_api_endpoint: str = "https://api.anthropic.com/v1/messages"
    anthropic_api_key: SecretStr | None = None
    anthropic_model_aliases: dict[str, str] = Field(default_factory=dict)
    ai_model_input_cost_per_million: dict[str, Decimal] = Field(default_factory=dict)
    ai_model_output_cost_per_million: dict[str, Decimal] = Field(default_factory=dict)
    ai_cost_currency: str = "USD"
    ai_agent_turn_timeout_seconds: float = Field(default=45, ge=1, le=180)
    ai_cancellation_poll_seconds: float = Field(default=0.5, ge=0.1, le=5)
    ai_conversation_max_messages: int = Field(default=20, ge=2, le=100)
    ai_conversation_max_context_characters: int = Field(default=24_000, ge=1000, le=100_000)
    ai_employee_max_evidence: int = Field(default=5, ge=1, le=12)
    ai_employee_minimum_evidence_score: float = Field(default=0.01, ge=0, le=10)
    ai_stream_chunk_characters: int = Field(default=120, ge=20, le=1000)
    oracle_document_acquisition_enabled: bool = False
    retrieval_max_results: int = Field(default=20, ge=1, le=50)
    retrieval_statement_timeout_ms: int = Field(default=1500, ge=50, le=30000)
    retrieval_timeout_seconds: float = Field(default=2.0, ge=0.1, le=60)
    retrieval_embedding_provider: Literal["deterministic", "http"] = "deterministic"
    retrieval_embedding_endpoint: str | None = None
    retrieval_embedding_api_key: SecretStr | None = None
    retrieval_embedding_model_code: str = "DEFAULT_1536"
    retrieval_provider_timeout_seconds: float = Field(default=10, ge=1, le=60)
    retrieval_reranker_enabled: bool = False
    retrieval_reranker_endpoint: str | None = None
    retrieval_reranker_api_key: SecretStr | None = None
    retrieval_reranker_model_code: str = "APPROVED_RERANKER"

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

        retrieval_errors: list[str] = []
        if self.retrieval_embedding_provider == "http":
            if not self.retrieval_embedding_endpoint:
                retrieval_errors.append("RETRIEVAL_EMBEDDING_ENDPOINT is required")
            if self.retrieval_embedding_api_key is None:
                retrieval_errors.append("RETRIEVAL_EMBEDDING_API_KEY is required")
        if self.retrieval_reranker_enabled:
            if not self.retrieval_reranker_endpoint:
                retrieval_errors.append("RETRIEVAL_RERANKER_ENDPOINT is required")
            if self.retrieval_reranker_api_key is None:
                retrieval_errors.append("RETRIEVAL_RERANKER_API_KEY is required")
        provider_errors: list[str] = []
        if self.ai_globally_enabled:
            if not self.openai_model_aliases and not self.anthropic_model_aliases:
                provider_errors.append("at least one AI model alias is required")
            if self.openai_model_aliases and self.openai_api_key is None:
                provider_errors.append("OPENAI_API_KEY is required for OpenAI aliases")
            if self.openai_model_aliases and not self.openai_api_endpoint.startswith("https://"):
                provider_errors.append("OPENAI_API_ENDPOINT must use HTTPS")
            if self.anthropic_model_aliases and self.anthropic_api_key is None:
                provider_errors.append("ANTHROPIC_API_KEY is required for Anthropic aliases")
            if self.anthropic_model_aliases and not self.anthropic_api_endpoint.startswith(
                "https://"
            ):
                provider_errors.append("ANTHROPIC_API_ENDPOINT must use HTTPS")
        if provider_errors:
            raise ValueError("Invalid AI provider configuration: " + "; ".join(provider_errors))
        if retrieval_errors:
            raise ValueError(
                "Invalid retrieval provider configuration: " + "; ".join(retrieval_errors)
            )

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
            if self.object_storage_server_side_encryption is None:
                errors.append("OBJECT_STORAGE_SERVER_SIDE_ENCRYPTION is required")
            if (
                self.object_storage_server_side_encryption == "aws:kms"
                and self.object_storage_sse_key_id is None
            ):
                errors.append("OBJECT_STORAGE_SSE_KEY_ID is required for aws:kms")
            if not self.clamav_required:
                errors.append("CLAMAV_REQUIRED must be true")
        if self.retrieval_embedding_provider != "http":
            errors.append("RETRIEVAL_EMBEDDING_PROVIDER must be http")
        if (
            not self.retrieval_embedding_endpoint
            or not self.retrieval_embedding_endpoint.startswith("https://")
        ):
            errors.append("RETRIEVAL_EMBEDDING_ENDPOINT must use HTTPS")
        if self.retrieval_embedding_api_key is None:
            errors.append("RETRIEVAL_EMBEDDING_API_KEY is required")
        if self.retrieval_reranker_enabled:
            if (
                not self.retrieval_reranker_endpoint
                or not self.retrieval_reranker_endpoint.startswith("https://")
            ):
                errors.append("RETRIEVAL_RERANKER_ENDPOINT must use HTTPS")
            if self.retrieval_reranker_api_key is None:
                errors.append("RETRIEVAL_RERANKER_API_KEY is required")
        if self.ai_globally_enabled:
            if not self.openai_api_endpoint.startswith("https://"):
                errors.append("OPENAI_API_ENDPOINT must use HTTPS")
            if not self.anthropic_api_endpoint.startswith("https://"):
                errors.append("ANTHROPIC_API_ENDPOINT must use HTTPS")
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

    @field_validator("ai_cost_currency")
    @classmethod
    def validate_ai_cost_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("AI_COST_CURRENCY must be a three-letter currency code")
        return normalized

    @field_validator("ai_model_input_cost_per_million", "ai_model_output_cost_per_million")
    @classmethod
    def validate_ai_cost_rates(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if any(not alias.strip() or rate < 0 for alias, rate in value.items()):
            raise ValueError(
                "AI model cost rates require non-empty aliases and non-negative values"
            )
        return value

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
