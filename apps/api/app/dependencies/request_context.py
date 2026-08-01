"""Request-context dependency for future application services."""

from fastapi import Request

from apps.api.app.core.context import RequestContext


def get_request_context(request: Request) -> RequestContext:
    context = getattr(request.state, "request_context", None)
    if not isinstance(context, RequestContext):
        raise RuntimeError("Request context middleware is not installed")
    return context
