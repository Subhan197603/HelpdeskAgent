"""Contracts for retrieval quality analytics and gap dispositions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RetrievalAnalyticsGroupKind = Literal["ZERO_RESULT", "LOW_CONFIDENCE"]
GapDispositionStatus = Literal[
    "ACKNOWLEDGED",
    "SOURCE_CANDIDATE",
    "NOT_A_GAP",
    "RESOLVED",
]


class KnowledgeGapDispositionResponse(BaseModel):
    disposition_status: GapDispositionStatus
    disposition_note: str | None
    decided_at: datetime
    row_version: int
    replayed: bool = False


class KnowledgeGapDispositionCommand(BaseModel):
    normalized_query: str = Field(min_length=1, max_length=500)
    disposition_status: GapDispositionStatus
    disposition_note: str | None = Field(default=None, max_length=500)
    expected_row_version: int | None = Field(default=None, ge=1)


class RetrievalAnalyticsSummaryResponse(BaseModel):
    window_days: int
    low_confidence_threshold: float
    event_count: int = 0
    zero_result_count: int = 0
    zero_result_rate: float = 0.0
    low_confidence_count: int = 0
    low_confidence_rate: float = 0.0
    expansion_applied_count: int = 0
    expansion_applied_rate: float = 0.0
    query_group_count: int = 0


class RetrievalQueryGroupResponse(BaseModel):
    kind: RetrievalAnalyticsGroupKind
    normalized_query: str
    event_count: int
    matching_count: int
    expanded_event_count: int = 0
    expanded_zero_result_count: int = 0
    unexpanded_zero_result_count: int = 0
    best_top_score: float | None
    surfaces: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    last_corpus_version_id: UUID | None
    disposition: KnowledgeGapDispositionResponse | None = None


class RetrievalQueryGroupListResponse(BaseModel):
    window_days: int
    low_confidence_threshold: float
    items: list[RetrievalQueryGroupResponse]
    has_more: bool = False
