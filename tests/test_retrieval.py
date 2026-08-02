"""Authorization, normalization, bounds, and cancellation tests for retrieval."""

import asyncio
from typing import Any, cast
from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.core.settings import Environment, Settings
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.retrieval.fusion import fuse_candidates
from apps.api.app.retrieval.models import (
    CandidateKind,
    RetrievalCandidate,
    RetrievalConfiguration,
    RetrievalFilters,
    RetrievalRequest,
)
from apps.api.app.retrieval.normalization import InvalidRetrievalQuery, normalize_query
from apps.api.app.retrieval.repository import RetrievalRepository
from apps.api.app.retrieval.service import (
    RetrievalDeadlineExceeded,
    RetrievalRequestError,
    RetrievalService,
)

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")
CHUNK_ONE = UUID("72000000-0000-0000-0000-000000000001")
CHUNK_TWO = UUID("72000000-0000-0000-0000-000000000002")


class SpyEmbeddings:
    model_code = "DEFAULT_1536"

    def __init__(self) -> None:
        self.called = False

    async def embed(self, query: str) -> tuple[float, ...]:
        del query
        self.called = True
        return (0.0,) * 1536


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


def _candidate(
    chunk_id: UUID,
    rank: int,
    kind: CandidateKind,
    score: float,
    *,
    content: str,
    release: str = "26C",
    module: str = "AP",
    source_type: str = "ORACLE_PUBLIC_DOCUMENTATION",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        rank=rank,
        kind=kind,
        chunk_id=chunk_id,
        document_id=UUID(int=chunk_id.int + 10),
        document_version_id=UUID(int=chunk_id.int + 20),
        source_id=UUID(int=chunk_id.int + 30),
        document_title="Invoice validation holds",
        heading_path="Payables > Holds",
        content_text=content,
        language_code="en",
        release_family="FUSION_APPLICATIONS",
        release_code=release,
        product_code="FINANCIALS",
        product_name="Financials",
        module_code=module,
        module_name="Accounts Payable",
        source_type=source_type,
        canonical_uri="https://docs.example.test/payables/holds",
        section_title="Validation holds",
        section_anchor="validation-holds",
        page_number=123,
        score=score,
    )


def _configuration(**changes: object) -> RetrievalConfiguration:
    values: dict[str, object] = {
        "version_id": UUID("71000000-0000-0000-0000-000000000002"),
        "rrf_k": 60,
        "lexical_weight": 1.0,
        "vector_weight": 1.0,
        "exact_identifier_boost": 0.35,
        "metadata_boost": 0.08,
        "rerank_weight": 0.25,
        "reranking_enabled": False,
        "source_authority_weights": {"ORACLE_PUBLIC_DOCUMENTATION": 0.06},
    }
    values.update(changes)
    return RetrievalConfiguration(**values)  # type: ignore[arg-type]


def test_fusion_normalizes_scores_boosts_exact_identifiers_and_is_deterministic() -> None:
    lexical = (
        _candidate(CHUNK_ONE, 1, CandidateKind.LEXICAL, 4.0, content="Resolve AP-810 hold"),
        _candidate(CHUNK_TWO, 2, CandidateKind.LEXICAL, 1.0, content="Generic invoice help"),
    )
    vector = (
        _candidate(CHUNK_TWO, 1, CandidateKind.VECTOR, 0.9, content="Generic invoice help"),
        _candidate(CHUNK_ONE, 2, CandidateKind.VECTOR, 0.7, content="Resolve AP-810 hold"),
    )
    filters = RetrievalFilters(
        product_codes=("FINANCIALS",),
        module_codes=("AP",),
        release_families=("FUSION_APPLICATIONS",),
        release_codes=("26C",),
    )
    result = fuse_candidates(
        "AP-810 invoice hold 26C",
        lexical,
        vector,
        filters,
        _configuration(),
        limit=2,
    )
    assert [item.chunk_id for item in result] == [CHUNK_ONE, CHUNK_TWO]
    assert result[0].components.lexical == 1.0
    assert result[1].components.vector == 1.0
    assert result[0].components.exact_identifier_boost == 0.35
    assert result[1].components.exact_identifier_boost == 0.0
    assert result[0].components.metadata_boost == 0.32
    assert result[0].components.source_authority_boost == 0.06
    assert [item.rank for item in result] == [1, 2]


def test_optional_reranker_can_change_rank_without_exposing_configuration() -> None:
    lexical = (
        _candidate(CHUNK_ONE, 1, CandidateKind.LEXICAL, 2.0, content="Invoice hold"),
        _candidate(CHUNK_TWO, 2, CandidateKind.LEXICAL, 1.0, content="Invoice hold"),
    )
    result = fuse_candidates(
        "invoice hold",
        lexical,
        (),
        RetrievalFilters(),
        _configuration(reranking_enabled=True, rerank_weight=1.0),
        {CHUNK_ONE: 0.1, CHUNK_TWO: 0.9},
        limit=2,
    )
    assert [item.chunk_id for item in result] == [CHUNK_TWO, CHUNK_ONE]
    assert result[0].components.rerank == 0.9


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


def test_evidence_denies_unauthorized_persona_before_provider_call() -> None:
    embeddings = SpyEmbeddings()
    service = RetrievalService(
        cast("Any", lambda _: FakeUnitOfWork()),
        AuthorizationService(),
        Settings(app_env=Environment.TEST),
        embeddings,
    )
    with pytest.raises(AuthorizationError):
        asyncio.run(
            service.evidence(
                _context("CUSTOMER"),
                query="analyst-only procedure",
                filters=RetrievalFilters(),
                limit=8,
                persona="ANALYST",
            )
        )
    assert not embeddings.called


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
