"""ASGI middleware for request identity and secure response defaults."""

import logging
import re
import time
from collections.abc import MutableMapping
from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.api.app.core.context import (
    RequestContext,
    reset_current_request_context,
    set_current_request_context,
)

CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"
_HEADER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
logger = logging.getLogger(__name__)


def valid_correlation_id(value: str | None) -> bool:
    if value is None or not _HEADER_PATTERN.fullmatch(value):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get(CORRELATION_ID_HEADER)
        correlation_id = (
            incoming if incoming is not None and valid_correlation_id(incoming) else str(uuid4())
        )
        request_id = str(uuid4())
        context = RequestContext.anonymous(correlation_id, request_id)
        state = scope.setdefault("state", {})
        if isinstance(state, MutableMapping):
            state["correlation_id"] = correlation_id
            state["request_id"] = request_id
            state["request_context"] = context

        token = set_current_request_context(context)
        started = time.perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[CORRELATION_ID_HEADER] = correlation_id
                response_headers[REQUEST_ID_HEADER] = request_id
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["Content-Security-Policy"] = "default-src 'none'"
                if self.hsts:
                    response_headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            logger.exception("Unhandled request error", extra={"error_code": "internal_error"})
            response = JSONResponse(
                {
                    "type": "https://helpdesk.example/problems/internal-error",
                    "title": "Internal server error",
                    "status": 500,
                    "detail": "An unexpected error occurred.",
                    "instance": scope.get("path", ""),
                    "correlation_id": correlation_id,
                },
                status_code=500,
                media_type="application/problem+json",
            )
            await response(scope, receive, send_with_context)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            logger.info(
                "Request completed",
                extra={
                    "http_method": scope.get("method"),
                    "http_path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "outcome": "success" if status_code < 400 else "failure",
                },
            )
            reset_current_request_context(token)
