"""Application logging configuration with request-aware structured fields."""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from apps.api.app.core.context import get_current_request_context
from apps.api.app.core.settings import Settings

_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


def _safe_context_fields() -> dict[str, str | None]:
    context = get_current_request_context()
    if context is None:
        return {"correlation_id": None, "request_id": None, "tenant_id": None, "user_id_hash": None}
    user_hash = None
    if context.user_id is not None:
        user_hash = hashlib.sha256(str(context.user_id).encode()).hexdigest()[:16]
    return {
        "correlation_id": context.correlation_id,
        "request_id": context.request_id,
        "tenant_id": str(context.tenant_id) if context.tenant_id else None,
        "user_id_hash": user_hash,
    }


class JsonFormatter(logging.Formatter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.settings.app_name,
            "env": self.settings.app_env.value,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": None,
            "http_method": None,
            "http_path": None,
            "status_code": None,
            "duration_ms": None,
            "outcome": None,
            "error_code": None,
            **_safe_context_fields(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and key not in {"message", "asctime"}:
                payload[key] = value
        return json.dumps(payload, default=str, separators=(",", ":"))


class ReadableFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = _safe_context_fields()
        suffix = f" correlation_id={context['correlation_id']}" if context["correlation_id"] else ""
        return f"{record.levelname:<8} {record.name}: {record.getMessage()}{suffix}"


def configure_logging(settings: Settings) -> None:
    """Install exactly one application-owned root handler."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_fusion_helpdesk", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler._fusion_helpdesk = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter(settings) if settings.json_logs else ReadableFormatter())
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
