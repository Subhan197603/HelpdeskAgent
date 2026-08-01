"""Concurrency-safe request metadata used by logs and service boundaries."""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Immutable caller context; absent identity fields mean an anonymous caller."""

    tenant_id: UUID | None
    user_id: UUID | None
    external_subject: str | None
    roles: frozenset[str]
    support_group_ids: frozenset[UUID]
    business_unit_id: UUID | None
    correlation_id: str
    request_id: str

    @classmethod
    def anonymous(cls, correlation_id: str, request_id: str) -> "RequestContext":
        return cls(None, None, None, frozenset(), frozenset(), None, correlation_id, request_id)

    @property
    def is_authenticated(self) -> bool:
        return (
            self.tenant_id is not None
            and self.user_id is not None
            and self.external_subject is not None
        )


_request_context: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def get_current_request_context() -> RequestContext | None:
    return _request_context.get()


def set_current_request_context(context: RequestContext) -> Token[RequestContext | None]:
    return _request_context.set(context)


def reset_current_request_context(token: Token[RequestContext | None]) -> None:
    _request_context.reset(token)
