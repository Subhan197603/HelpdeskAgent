"""Governed error-code matching determinism, gating, and fail-open tests."""

from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.retrieval.error_code_matching import (
    matched_error_code_count,
    matching_tenant_ids,
    query_error_codes,
)
from apps.api.app.retrieval.fusion import _identifiers, fuse_candidates
from apps.api.app.retrieval.models import (
    CandidateKind,
    RetrievalCandidate,
    RetrievalConfiguration,
    RetrievalFilters,
)
from apps.api.app.retrieval.repository import RetrievalPrincipal
from apps.api.app.retrieval.service import RetrievalService

from .conftest import make_test_settings

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")
CHUNK_ONE = UUID("72000000-0000-0000-0000-000000000001")
CHUNK_TWO = UUID("72000000-0000-0000-0000-000000000002")
CHUNK_THREE = UUID("72000000-0000-0000-0000-000000000003")


def test_matching_defaults_are_off() -> None:
    settings = make_test_settings()
    assert settings.retrieval_error_code_matching_enabled is False
    assert settings.retrieval_error_code_matching_tenant_ids == ""


def test_tenant_allowlist_parsing_is_bounded_and_normalized() -> None:
    assert matching_tenant_ids("") == frozenset()
    assert matching_tenant_ids(" A , b ,, ") == frozenset({"a", "b"})


def test_query_error_codes_match_the_fusion_grammar() -> None:
    query = "ap-810 hold after ora_600 during import"
    assert query_error_codes(query) == ("AP-810", "ORA-600")
    assert frozenset(query_error_codes(query)) == _identifiers(query)
    assert query_error_codes("no codes in plain prose") == ()


def test_matched_code_count_counts_distinct_evidenced_codes() -> None:
    candidates = (
        _candidate(CHUNK_ONE, 1, content="Resolve AP-810 holds and ORA-600 faults"),
        _candidate(CHUNK_TWO, 2, content="More AP-810 background"),
    )
    assert matched_error_code_count(candidates, ("AP-810", "ORA-600", "ZZZ-999")) == 2
    assert matched_error_code_count((), ("AP-810",)) == 0


def test_fusion_scores_matched_candidates_through_the_unchanged_formula() -> None:
    lexical = (_candidate(CHUNK_ONE, 1, kind=CandidateKind.LEXICAL, content="Generic help"),)
    vector = (_candidate(CHUNK_TWO, 1, kind=CandidateKind.VECTOR, content="Generic help"),)
    matched = (_candidate(CHUNK_THREE, 1, content="AP-810 hold runbook"),)
    evidence = fuse_candidates(
        "resolve ap-810 hold",
        lexical,
        vector,
        RetrievalFilters(),
        _configuration(),
        error_code_matches=matched,
        limit=10,
    )
    by_chunk = {item.chunk_id: item for item in evidence}
    injected = by_chunk[CHUNK_THREE]
    # No lexical or vector rank: the unchanged formula yields zero fusion and
    # scores the match through the existing boosts alone.
    assert injected.components.lexical is None
    assert injected.components.vector is None
    assert injected.components.fusion == 0.0
    assert injected.components.exact_identifier_boost == 0.35
    assert injected.score == pytest.approx(0.35 + 0.06)


def test_fusion_collapses_matches_onto_ranked_channels() -> None:
    lexical = (_candidate(CHUNK_ONE, 1, kind=CandidateKind.LEXICAL, content="AP-810 hold"),)
    matched = (_candidate(CHUNK_ONE, 1, content="AP-810 hold"),)
    evidence = fuse_candidates(
        "resolve ap-810 hold",
        lexical,
        (),
        RetrievalFilters(),
        _configuration(),
        error_code_matches=matched,
        limit=10,
    )
    assert len(evidence) == 1
    assert evidence[0].components.lexical is not None


def test_fusion_default_is_byte_equal_without_matches() -> None:
    lexical = (_candidate(CHUNK_ONE, 1, kind=CandidateKind.LEXICAL, content="AP-810 hold"),)
    vector = (_candidate(CHUNK_TWO, 1, kind=CandidateKind.VECTOR, content="Generic help"),)
    arguments = ("resolve ap-810 hold", lexical, vector, RetrievalFilters(), _configuration())
    assert fuse_candidates(*arguments, limit=10) == fuse_candidates(
        *arguments, error_code_matches=(), limit=10
    )


@pytest.mark.anyio
async def test_disabled_switch_skips_matching_without_database() -> None:
    service = _service(make_test_settings())
    result = await service._error_code_matches(
        _context(), _principal(), "ap-810 hold", RetrievalFilters(), 10
    )
    assert result.applied is False
    assert result.candidates == ()


@pytest.mark.anyio
async def test_unlisted_tenant_skips_matching_without_database() -> None:
    settings = make_test_settings(
        retrieval_error_code_matching_enabled=True,
        retrieval_error_code_matching_tenant_ids="99999999-0000-0000-0000-000000000001",
    )
    result = await _service(settings)._error_code_matches(
        _context(), _principal(), "ap-810 hold", RetrievalFilters(), 10
    )
    assert result.applied is False


@pytest.mark.anyio
async def test_query_without_codes_skips_matching_without_database() -> None:
    settings = make_test_settings(
        retrieval_error_code_matching_enabled=True,
        retrieval_error_code_matching_tenant_ids=str(TENANT),
    )
    result = await _service(settings)._error_code_matches(
        _context(), _principal(), "printer keeps jamming", RetrievalFilters(), 10
    )
    assert result.applied is False


@pytest.mark.anyio
async def test_matching_failure_falls_back_to_unmatched_candidates() -> None:
    def broken_factory(_: RequestContext) -> object:
        raise RuntimeError("index unavailable")

    settings = make_test_settings(
        retrieval_error_code_matching_enabled=True,
        retrieval_error_code_matching_tenant_ids=str(TENANT),
    )
    service = RetrievalService(
        broken_factory,  # type: ignore[arg-type]
        AuthorizationService(),
        settings,
    )
    result = await service._error_code_matches(
        _context(), _principal(), "ap-810 hold", RetrievalFilters(), 10
    )
    assert result.applied is False
    assert result.candidates == ()


def _service(settings: object) -> RetrievalService:
    def factory(_: RequestContext) -> object:
        raise AssertionError("gated-off matching must not open a unit of work")

    return RetrievalService(
        factory,  # type: ignore[arg-type]
        AuthorizationService(),
        settings,  # type: ignore[arg-type]
    )


def _context() -> RequestContext:
    return RequestContext(
        TENANT,
        USER,
        "retrieval-error-code",
        frozenset({"EMPLOYEE"}),
        frozenset(),
        None,
        str(TENANT),
        "retrieval-error-code",
    )


def _principal() -> RetrievalPrincipal:
    return RetrievalPrincipal(
        tenant_id=TENANT,
        user_id=USER,
        role_codes=("EMPLOYEE",),
        support_group_codes=(),
        business_unit_code=None,
        audience_codes=("ALL", "EMPLOYEE"),
        security_levels=("PUBLIC", "INTERNAL"),
        persona="EMPLOYEE",
    )


def _candidate(
    chunk_id: UUID,
    rank: int,
    *,
    kind: CandidateKind = CandidateKind.ERROR_CODE,
    content: str,
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
        release_code="26C",
        product_code="FINANCIALS",
        product_name="Financials",
        module_code="AP",
        module_name="Accounts Payable",
        source_type="ORACLE_PUBLIC_DOCUMENTATION",
        canonical_uri="https://docs.example.test/payables/holds",
        section_title="Validation holds",
        section_anchor="validation-holds",
        page_number=123,
        score=1.0,
    )


def _configuration() -> RetrievalConfiguration:
    return RetrievalConfiguration(
        version_id=UUID("71000000-0000-0000-0000-000000000002"),
        rrf_k=60,
        lexical_weight=1.0,
        vector_weight=1.0,
        exact_identifier_boost=0.35,
        metadata_boost=0.08,
        rerank_weight=0.25,
        reranking_enabled=False,
        source_authority_weights={"ORACLE_PUBLIC_DOCUMENTATION": 0.06},
    )
