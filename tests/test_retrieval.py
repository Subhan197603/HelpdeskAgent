"""Authorization, normalization, bounds, and cancellation tests for retrieval."""

import asyncio
from typing import Any, cast
from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.core.settings import Environment, Settings
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.retrieval.models import RetrievalFilters, RetrievalRequest
from apps.api.app.retrieval.normalization import InvalidRetrievalQuery, normalize_query
from apps.api.app.retrieval.repository import RetrievalRepository
from apps.api.app.retrieval.service import (
    RetrievalDeadlineExceeded,
    RetrievalRequestError,
    RetrievalService,
)

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.session = cast("Any", object())
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


def _context(role: str) -> RequestContext:
    return RequestContext(
        tenant_id=TENANT,
        user_id=USER,
        external_subject=f"retrieval-{role.lower()}",
        roles=frozenset({role}),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id=str(TENANT),
        request_id="retrieval-unit",
    )


def _request(**changes: object) -> RetrievalRequest:
    values: dict[str, object] = {
        "query": "  Invoice\u00a0Validation\tHolds  ",
        "query_embedding": (0.0,) * 1536,
    }
    values.update(changes)
    return RetrievalRequest(**values)  # type: ignore[arg-type]


def test_query_normalization_is_unicode_stable_bounded_and_nonempty() -> None:
    assert normalize_query("  FUSION\u00a0AP\t26C  ") == "fusion ap 26c"
    assert normalize_query("ＡＰ\u200b Holds") == "ap holds"
    with pytest.raises(InvalidRetrievalQuery, match="empty"):
        normalize_query("\u200b\t")
    with pytest.raises(InvalidRetrievalQuery, match="limit"):
        normalize_query("x" * 501)


def test_retrieval_permissions_distinguish_employee_and_analyst() -> None:
    authorization = AuthorizationService()
    customer = _context("CUSTOMER")
    analyst = _context("AGENT")
    assert authorization.is_allowed(customer, Permission.KNOWLEDGE_READ_EMPLOYEE)
    assert not authorization.is_allowed(customer, Permission.KNOWLEDGE_READ_ANALYST)
    assert authorization.is_allowed(analyst, Permission.KNOWLEDGE_READ_EMPLOYEE)
    assert authorization.is_allowed(analyst, Permission.KNOWLEDGE_READ_ANALYST)


def test_service_normalizes_filters_and_keeps_candidate_lists_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def lexical(
        self: RetrievalRepository,
        principal: object,
        query: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> tuple[()]:
        del self
        observed.update(principal=principal, query=query, filters=filters, limit=limit)
        return ()

    async def vector(self: RetrievalRepository, *_: object) -> tuple[()]:
        del self
        return ()

    monkeypatch.setattr(RetrievalRepository, "lexical", lexical)
    monkeypatch.setattr(RetrievalRepository, "vector", vector)
    uow = FakeUnitOfWork()
    service = RetrievalService(
        cast("Any", lambda _: uow),
        AuthorizationService(),
        Settings(app_env=Environment.TEST),
    )
    result = asyncio.run(
        service.search(
            _context("CUSTOMER"),
            _request(
                filters=RetrievalFilters(
                    product_codes=(" ap ", "AP"),
                    release_families=("fusion_applications",),
                    release_codes=("26c",),
                    language_codes=("EN",),
                )
            ),
        )
    )
    assert result.normalized_query == "invoice validation holds"
    assert result.lexical == () and result.vector == ()
    assert observed["query"] == result.normalized_query
    assert observed["filters"] == RetrievalFilters(
        product_codes=("AP",),
        release_families=("FUSION_APPLICATIONS",),
        release_codes=("26C",),
        language_codes=("en",),
    )
    assert uow.committed


@pytest.mark.parametrize(
    "retrieval_request",
    [
        _request(query_embedding=(0.0,) * 10),
        _request(query_embedding=(float("nan"),) + (0.0,) * 1535),
        _request(limit=0),
        _request(limit=21),
    ],
)
def test_service_rejects_unbounded_or_invalid_requests(
    retrieval_request: RetrievalRequest,
) -> None:
    service = RetrievalService(
        cast("Any", lambda _: FakeUnitOfWork()),
        AuthorizationService(),
        Settings(app_env=Environment.TEST),
    )
    with pytest.raises(RetrievalRequestError):
        asyncio.run(service.search(_context("CUSTOMER"), retrieval_request))


def test_customer_cannot_request_analyst_retrieval() -> None:
    service = RetrievalService(
        cast("Any", lambda _: FakeUnitOfWork()),
        AuthorizationService(),
        Settings(app_env=Environment.TEST),
    )
    with pytest.raises(AuthorizationError):
        asyncio.run(service.search(_context("CUSTOMER"), _request(persona="ANALYST")))


def test_service_cancels_slow_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(*_: object) -> tuple[()]:
        await asyncio.sleep(0.2)
        return ()

    monkeypatch.setattr(RetrievalRepository, "lexical", slow)
    service = RetrievalService(
        cast("Any", lambda _: FakeUnitOfWork()),
        AuthorizationService(),
        Settings(app_env=Environment.TEST, retrieval_timeout_seconds=0.1),
    )
    with pytest.raises(RetrievalDeadlineExceeded):
        asyncio.run(service.search(_context("CUSTOMER"), _request()))
