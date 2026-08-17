"""Human-triggered corpus validation report endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.corpus_validation_schemas import (
    CorpusFindingType,
    CorpusValidationReportResponse,
)
from apps.api.app.knowledge.corpus_validation_service import CorpusValidationService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Corpus validation permission denied"},
    404: {"model": ProblemResponse, "description": "Corpus validation run not found"},
    409: {"model": ProblemResponse, "description": "Corpus validation conflict"},
    422: {"model": ProblemResponse, "description": "Corpus validation request invalid"},
}
router = APIRouter(
    prefix="/api/v1/admin/knowledge/corpus-validations", tags=["knowledge-publication"]
)
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _service(request: Request) -> CorpusValidationService:
    return cast("CorpusValidationService", request.app.state.corpus_validation_service)


@router.post(
    "",
    response_model=CorpusValidationReportResponse,
    status_code=201,
    responses=ERRORS,
)
async def run_corpus_validation(
    response: Response,
    request: Request,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_PUBLISH, privileged_access=True)),
    ],
) -> CorpusValidationReportResponse:
    result = await _service(request).run_validation(context, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get("/latest", response_model=CorpusValidationReportResponse, responses=ERRORS)
async def latest_corpus_validation(
    request: Request,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
    ],
) -> CorpusValidationReportResponse:
    return await _service(request).latest_report(context)


@router.get("/{run_id}", response_model=CorpusValidationReportResponse, responses=ERRORS)
async def get_corpus_validation(
    request: Request,
    run_id: UUID,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
    ],
    finding_type: CorpusFindingType | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CorpusValidationReportResponse:
    return await _service(request).report(
        context, run_id, finding_type=finding_type, limit=limit, offset=offset
    )
