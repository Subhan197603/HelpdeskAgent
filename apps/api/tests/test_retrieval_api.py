"""Evidence API authorization and public-contract tests."""

from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_authenticated_context
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app
from apps.api.app.retrieval.models import (
    RetrievalEvidence,
    RetrievalEvidenceSet,
    ScoreComponents,
)
from apps.api.app.retrieval.service import RetrievalService

from .conftest import FakeProbe, make_test_settings

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")


class FakeRetrievalService:
    async def evidence(self, *_: object, **__: object) -> RetrievalEvidenceSet:
        item_id = UUID("72000000-0000-0000-0000-000000000001")
        return RetrievalEvidenceSet(
            normalized_query="ap invoice hold 26c",
            retrieval_configuration_version_id=UUID("71000000-0000-0000-0000-000000000002"),
            evidence=(
                RetrievalEvidence(
                    rank=1,
                    chunk_id=item_id,
                    document_id=UUID(int=item_id.int + 1),
                    document_version_id=UUID(int=item_id.int + 2),
                    source_id=UUID(int=item_id.int + 3),
                    document_title="Resolve invoice validation holds",
                    heading_path="Payables > Holds",
                    section_title="Validation holds",
                    section_anchor="validation-holds",
                    content_text="Resolve the AP invoice hold.",
                    language_code="en",
                    release_family="FUSION_APPLICATIONS",
                    release_code="26C",
                    product_code="FINANCIALS",
                    product_name="Financials",
                    module_code="AP",
                    module_name="Accounts Payable",
                    source_type="ORACLE_PUBLIC_DOCUMENTATION",
                    canonical_uri="https://docs.example.test/payables/holds",
                    page_number=123,
                    score=0.91,
                    components=ScoreComponents(0.8, 0.9, 0.86, 0, 0.16, 0.06, None),
                ),
            ),
        )


def _app() -> FastAPI:
    app = create_app(
        make_test_settings(),
        resource_factory=lambda _: ApplicationResources(
            FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe()
        ),
    )
    app.state.retrieval_service = cast("RetrievalService", FakeRetrievalService())
    app.dependency_overrides[require_authenticated_context] = lambda: RequestContext(
        TENANT,
        USER,
        "retrieval-api",
        frozenset({"CUSTOMER"}),
        frozenset(),
        None,
        str(TENANT),
        "retrieval-api",
    )
    return app


def test_evidence_api_returns_canonical_metadata_without_raw_configuration() -> None:
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/knowledge/evidence/search",
            json={
                "query": "AP invoice hold 26C",
                "filters": {
                    "module_codes": ["AP"],
                    "release_families": ["FUSION_APPLICATIONS"],
                    "release_codes": ["26C"],
                },
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"][0]["canonical_uri"].startswith("https://")
    assert payload["evidence"][0]["section_anchor"] == "validation-holds"
    assert "configuration_json" not in response.text
    assert "rrf_k" not in response.text
    assert "lexical_weight" not in response.text


def test_evidence_api_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/knowledge/evidence/search", json={"query": "invoice hold"})
    assert response.status_code == 401
