"""Query-event capture derivation and failure-isolation tests."""

from typing import Any
from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.retrieval.query_events import RetrievalQueryEventRepository
from apps.api.app.retrieval.service import RetrievalService

from .conftest import make_test_settings

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> None:
        self.calls.append((str(statement), parameters))


def _context(tenant_id: UUID | None = TENANT) -> RequestContext:
    return RequestContext(
        tenant_id,
        USER,
        "query-events",
        frozenset({"CUSTOMER"}),
        frozenset(),
        None,
        "query-events",
        "query-events",
    )


@pytest.mark.anyio
async def test_insert_event_derives_zero_result_flag_from_result_count() -> None:
    session = FakeSession()
    repository = RetrievalQueryEventRepository(session)  # type: ignore[arg-type]

    await repository.insert_event(
        tenant_id=TENANT,
        surface="EVIDENCE_SEARCH",
        normalized_query="ap invoice hold",
        result_count=0,
        top_score=None,
    )
    await repository.insert_event(
        tenant_id=TENANT,
        surface="EMPLOYEE_AGENT",
        normalized_query="reset password",
        result_count=3,
        top_score=0.91,
    )

    zero, hit = session.calls[0][1], session.calls[1][1]
    assert zero["zero_result_flag"] is True
    assert zero["top_score"] is None
    assert hit["zero_result_flag"] is False
    assert hit["result_count"] == 3
    assert hit["top_score"] == 0.91
    assert hit["surface"] == "EMPLOYEE_AGENT"
    assert all(call[1]["tenant_id"] == TENANT for call in session.calls)


@pytest.mark.anyio
async def test_enforce_retention_is_tenant_scoped_and_bounded() -> None:
    session = FakeSession()
    repository = RetrievalQueryEventRepository(session)  # type: ignore[arg-type]

    await repository.enforce_retention(tenant_id=TENANT, retention_days=180)

    statement, parameters = session.calls[0]
    assert "DELETE FROM kb.retrieval_query_event" in statement
    assert "tenant_id=:tenant_id" in statement
    assert parameters == {"tenant_id": TENANT, "retention_days": 180}


@pytest.mark.anyio
async def test_capture_failure_never_raises_into_retrieval() -> None:
    def broken_factory(_: RequestContext) -> Any:
        raise RuntimeError("event store unavailable")

    service = RetrievalService(broken_factory, AuthorizationService(), make_test_settings())

    await service._capture_query_event(
        _context(),
        surface="ANALYST_COPILOT",
        normalized_query="ap invoice hold",
        result_count=2,
        top_score=0.5,
    )


@pytest.mark.anyio
async def test_capture_without_tenant_is_contained() -> None:
    def unused_factory(_: RequestContext) -> Any:
        raise AssertionError("factory must not be reached without a tenant")

    service = RetrievalService(unused_factory, AuthorizationService(), make_test_settings())

    await service._capture_query_event(
        _context(tenant_id=None),
        surface="EVIDENCE_SEARCH",
        normalized_query="orphan query",
        result_count=0,
        top_score=None,
    )
