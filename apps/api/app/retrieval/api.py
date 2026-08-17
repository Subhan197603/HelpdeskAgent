"""Authorized knowledge-evidence search endpoint."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_authenticated_context
from apps.api.app.retrieval.models import RetrievalFilters
from apps.api.app.retrieval.schemas import (
    EvidenceItem,
    EvidenceScoreComponents,
    EvidenceSearchRequest,
    EvidenceSearchResponse,
)
from apps.api.app.retrieval.service import RetrievalService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Knowledge access denied"},
    409: {"model": ProblemResponse, "description": "Retrieval request conflict"},
    422: {"model": ProblemResponse, "description": "Retrieval validation failed"},
    503: {"model": ProblemResponse, "description": "Retrieval dependency unavailable"},
}
router = APIRouter(prefix="/api/v1/knowledge/evidence", tags=["knowledge-evidence"])


def _service(request: Request) -> RetrievalService:
    return cast("RetrievalService", request.app.state.retrieval_service)


@router.post("/search", response_model=EvidenceSearchResponse, responses=ERRORS)
async def search_evidence(
    request: Request,
    command: EvidenceSearchRequest,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
) -> EvidenceSearchResponse:
    filters = RetrievalFilters(
        product_codes=tuple(command.filters.product_codes),
        module_codes=tuple(command.filters.module_codes),
        release_families=tuple(command.filters.release_families),
        release_codes=tuple(command.filters.release_codes),
        language_codes=tuple(command.filters.language_codes),
        source_ids=tuple(command.filters.source_ids),
    )
    result = await _service(request).evidence(
        context,
        query=command.query,
        filters=filters,
        limit=command.limit,
        persona=command.persona,
        surface="EVIDENCE_SEARCH",
    )
    return EvidenceSearchResponse(
        normalized_query=result.normalized_query,
        retrieval_configuration_version_id=result.retrieval_configuration_version_id,
        evidence=[
            EvidenceItem(
                rank=item.rank,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                source_id=item.source_id,
                document_title=item.document_title,
                document_type=item.document_type,
                heading_path=item.heading_path,
                section_title=item.section_title,
                section_anchor=item.section_anchor,
                content=item.content_text,
                language_code=item.language_code,
                release_family=item.release_family,
                release_code=item.release_code,
                product_code=item.product_code,
                product_name=item.product_name,
                module_code=item.module_code,
                module_name=item.module_name,
                source_type=item.source_type,
                canonical_uri=item.canonical_uri,
                page_number=item.page_number,
                final_score=item.score,
                score_components=EvidenceScoreComponents(
                    lexical=item.components.lexical,
                    vector=item.components.vector,
                    fusion=item.components.fusion,
                    exact_identifier_boost=item.components.exact_identifier_boost,
                    metadata_boost=item.components.metadata_boost,
                    source_authority_boost=item.components.source_authority_boost,
                    rerank=item.components.rerank,
                ),
            )
            for item in result.evidence
        ],
    )
