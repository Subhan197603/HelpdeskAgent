"""Synonym registry contract, normalization, and authorization tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_authenticated_context
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.knowledge.retrieval_synonym_schemas import (
    RetrievalSynonymListResponse,
    RetrievalSynonymResponse,
)
from apps.api.app.knowledge.retrieval_synonym_service import (
    _ALLOWED_TRANSITIONS,
    RetrievalSynonymService,
    _entry_response,
    normalize_synonym_text,
)
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")
DECIDED = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)


def _row(term: str, expansion: str, status: str = "DRAFT") -> SimpleNamespace:
    return SimpleNamespace(
        synonym_id=uuid4(),
        term=term,
        expansion=expansion,
        synonym_status=status,
        synonym_note=None,
        decided_at=DECIDED,
        row_version=1,
    )


def test_normalization_lowercases_trims_and_collapses_whitespace() -> None:
    assert normalize_synonym_text("  VPN ") == "vpn"
    assert normalize_synonym_text("Virtual   Private\tNetwork") == "virtual private network"
    assert normalize_synonym_text("   ") == ""


def test_transition_set_is_deterministic() -> None:
    assert ("DRAFT", "APPROVED") in _ALLOWED_TRANSITIONS
    assert ("APPROVED", "RETIRED") in _ALLOWED_TRANSITIONS
    assert ("RETIRED", "DRAFT") in _ALLOWED_TRANSITIONS
    assert ("APPROVED", "DRAFT") not in _ALLOWED_TRANSITIONS
    assert ("RETIRED", "APPROVED") not in _ALLOWED_TRANSITIONS


def test_entry_response_maps_row_fields() -> None:
    entry = _entry_response(_row("vpn", "virtual private network", "APPROVED"), replayed=True)
    assert isinstance(entry, RetrievalSynonymResponse)
    assert entry.term == "vpn"
    assert entry.expansion == "virtual private network"
    assert entry.synonym_status == "APPROVED"
    assert entry.row_version == 1
    assert entry.replayed is True


class FakeSynonymService:
    async def list_entries(
        self,
        _: RequestContext,
        *,
        status: str | None,
        term: str | None,
        limit: int,
        offset: int,
    ) -> RetrievalSynonymListResponse:
        del status, term, offset
        rows = [_row("vpn", "virtual private network", "APPROVED"), _row("sso", "single sign on")]
        return RetrievalSynonymListResponse(
            items=[_entry_response(row, replayed=False) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )


def _app() -> FastAPI:
    app = create_app(
        make_test_settings(),
        resource_factory=lambda _: ApplicationResources(
            FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe()
        ),
    )
    app.state.retrieval_synonym_service = cast("RetrievalSynonymService", FakeSynonymService())
    app.dependency_overrides[require_authenticated_context] = lambda: RequestContext(
        TENANT,
        USER,
        "retrieval-synonyms",
        frozenset({"KNOWLEDGE_AUTHOR"}),
        frozenset(),
        None,
        str(TENANT),
        "retrieval-synonyms",
    )
    return app


def test_listing_endpoint_returns_entries_and_has_more() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/admin/knowledge/retrieval-synonyms", params={"limit": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["has_more"] is True
    assert payload["items"][0]["term"] == "vpn"
    assert payload["items"][0]["synonym_status"] == "APPROVED"


def test_synonyms_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/admin/knowledge/retrieval-synonyms").status_code == 401
    assert (
        client.put(
            "/api/v1/admin/knowledge/retrieval-synonyms",
            json={"term": "vpn", "expansion": "virtual private network"},
            headers={"Idempotency-Key": "synonym-auth-check"},
        ).status_code
        == 401
    )
