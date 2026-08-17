"""Retrieval analytics contract, classification, and pagination tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_authenticated_context
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.knowledge.retrieval_analytics_schemas import (
    RetrievalAnalyticsSummaryResponse,
    RetrievalQueryGroupListResponse,
)
from apps.api.app.knowledge.retrieval_analytics_service import (
    RetrievalAnalyticsService,
    _rate,
)
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")
SEEN = datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)


def _row(query: str, matching: int, *, disposition_status: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        normalized_query=query,
        event_count=matching + 1,
        matching_count=matching,
        best_top_score=0.005,
        surfaces=["EMPLOYEE_AGENT", "EVIDENCE_SEARCH"],
        first_seen_at=SEEN,
        last_seen_at=SEEN,
        last_corpus_version_id=None,
        disposition_status=disposition_status,
        disposition_note="Covered by runbook" if disposition_status else None,
        disposition_decided_at=SEEN if disposition_status else None,
        disposition_row_version=2 if disposition_status else None,
    )


def _service() -> RetrievalAnalyticsService:
    def factory(_: RequestContext) -> object:
        raise AssertionError("listing mapping must not open a unit of work")

    return RetrievalAnalyticsService(
        factory,  # type: ignore[arg-type]
        AuthorizationService(),
        make_test_settings(),
    )


def test_rate_is_bounded_and_zero_safe() -> None:
    assert _rate(0, 0) == 0.0
    assert _rate(1, 3) == 0.3333
    assert _rate(3, 3) == 1.0


def test_listing_maps_rows_and_reports_has_more() -> None:
    listing = _service()._listing(
        "ZERO_RESULT",
        [
            _row("first", 3, disposition_status="SOURCE_CANDIDATE"),
            _row("second", 1),
            _row("overflow", 1),
        ],
        window_days=30,
        limit=2,
    )
    assert isinstance(listing, RetrievalQueryGroupListResponse)
    assert listing.has_more is True
    assert [item.normalized_query for item in listing.items] == ["first", "second"]
    assert listing.items[0].kind == "ZERO_RESULT"
    assert listing.items[0].surfaces == ["EMPLOYEE_AGENT", "EVIDENCE_SEARCH"]
    assert listing.items[0].best_top_score == 0.005
    assert listing.items[0].disposition is not None
    assert listing.items[0].disposition.disposition_status == "SOURCE_CANDIDATE"
    assert listing.items[0].disposition.row_version == 2
    assert listing.items[1].disposition is None
    assert listing.low_confidence_threshold == 0.01


class FakeAnalyticsService:
    async def summary(
        self, _: RequestContext, *, window_days: int
    ) -> RetrievalAnalyticsSummaryResponse:
        return RetrievalAnalyticsSummaryResponse(
            window_days=window_days,
            low_confidence_threshold=0.01,
            event_count=10,
            zero_result_count=4,
            zero_result_rate=0.4,
            low_confidence_count=2,
            low_confidence_rate=0.2,
            query_group_count=6,
        )


def _app() -> FastAPI:
    app = create_app(
        make_test_settings(),
        resource_factory=lambda _: ApplicationResources(
            FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe()
        ),
    )
    app.state.retrieval_analytics_service = cast(
        "RetrievalAnalyticsService", FakeAnalyticsService()
    )
    app.dependency_overrides[require_authenticated_context] = lambda: RequestContext(
        TENANT,
        USER,
        "retrieval-analytics",
        frozenset({"KNOWLEDGE_AUTHOR"}),
        frozenset(),
        None,
        str(TENANT),
        "retrieval-analytics",
    )
    return app


def test_summary_endpoint_returns_rates_for_read_admin() -> None:
    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/admin/knowledge/retrieval-analytics/summary",
            params={"days": 7},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["window_days"] == 7
    assert payload["zero_result_rate"] == 0.4
    assert payload["low_confidence_threshold"] == 0.01


def test_analytics_requires_authentication(client: TestClient) -> None:
    for path in ("summary", "zero-result-queries", "low-confidence-queries"):
        response = client.get(f"/api/v1/admin/knowledge/retrieval-analytics/{path}")
        assert response.status_code == 401
    assert (
        client.put(
            "/api/v1/admin/knowledge/retrieval-analytics/dispositions",
            json={"normalized_query": "q", "disposition_status": "ACKNOWLEDGED"},
            headers={"Idempotency-Key": "gap-disposition-401"},
        ).status_code
        == 401
    )
