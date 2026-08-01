"""RFC 7807-compatible exception responses."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from apps.api.app.core.exceptions import AppError


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "unknown"))


def _response(
    request: Request,
    status: int,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "type": payload.pop("type"),
        "title": payload.pop("title"),
        "status": status,
        "detail": payload.pop("detail"),
        "instance": request.url.path,
        "correlation_id": _correlation_id(request),
        **payload,
    }
    return JSONResponse(
        body,
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        extra: dict[str, Any] = {}
        if exc.field_errors:
            extra["errors"] = exc.field_errors
        return _response(
            request,
            exc.status_code,
            {"type": exc.problem_type, "title": exc.title, "detail": exc.detail, **extra},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors: dict[str, list[str]] = {}
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            field_errors.setdefault(location, []).append(str(error["msg"]))
        return _response(
            request,
            422,
            {
                "type": "https://helpdesk.example/problems/validation-failed",
                "title": "Validation failed",
                "detail": "The request did not pass validation.",
                "errors": field_errors,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return _response(
            request,
            exc.status_code,
            {
                "type": f"https://helpdesk.example/problems/http-{exc.status_code}",
                "title": "HTTP error",
                "detail": str(exc.detail),
            },
        )
