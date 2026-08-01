"""Application errors and their stable HTTP mappings."""

from collections.abc import Mapping, Sequence


class AppError(Exception):
    status_code = 500
    title = "Application error"
    error_code = "application_error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        field_errors: Mapping[str, Sequence[str]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.field_errors: dict[str, list[str]] | None = (
            {key: list(values) for key, values in field_errors.items()} if field_errors else None
        )
        self.headers = dict(headers or {})

    @property
    def problem_type(self) -> str:
        return f"https://helpdesk.example/problems/{self.error_code}"


class NotFoundError(AppError):
    status_code, title, error_code = 404, "Resource not found", "not_found"


class AuthorizationError(AppError):
    status_code, title, error_code = 403, "Access denied", "authorization_denied"


class AuthenticationError(AppError):
    status_code, title, error_code = 401, "Authentication required", "authentication_required"


class ValidationError(AppError):
    status_code, title, error_code = 422, "Validation failed", "validation_failed"


class ConflictError(AppError):
    status_code, title, error_code = 409, "Conflict", "conflict"


class InvalidTransitionError(AppError):
    status_code, title, error_code = 409, "Invalid transition", "invalid_transition"


class ConcurrencyError(AppError):
    status_code, title, error_code = 409, "Concurrent modification", "concurrency_error"


class DuplicateSubmissionError(AppError):
    status_code, title, error_code = 409, "Duplicate submission", "duplicate_submission"


class RateLimitError(AppError):
    status_code, title, error_code = 429, "Rate limit exceeded", "rate_limit_exceeded"


class ExternalDependencyError(AppError):
    status_code, title, error_code = 503, "External dependency unavailable", "external_dependency"


class KnowledgePermissionError(AppError):
    status_code, title, error_code = 403, "Knowledge access denied", "knowledge_permission"


class UnsupportedFileError(AppError):
    status_code, title, error_code = 415, "Unsupported file", "unsupported_file"


class MalwareDetectedError(AppError):
    status_code, title, error_code = 422, "Malware detected", "malware_detected"


class LLMProviderError(AppError):
    status_code, title, error_code = 503, "AI provider unavailable", "llm_provider"


__all__: list[str] = [
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "ConcurrencyError",
    "ConflictError",
    "DuplicateSubmissionError",
    "ExternalDependencyError",
    "InvalidTransitionError",
    "KnowledgePermissionError",
    "LLMProviderError",
    "MalwareDetectedError",
    "NotFoundError",
    "RateLimitError",
    "UnsupportedFileError",
    "ValidationError",
]
