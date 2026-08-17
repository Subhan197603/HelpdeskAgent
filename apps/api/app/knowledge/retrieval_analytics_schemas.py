"""Contracts for read-only retrieval quality analytics."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

RetrievalAnalyticsGroupKind = Literal["ZERO_RESULT", "LOW_CONFIDENCE"]


class RetrievalAnalyticsSummaryResponse(BaseModel):
    window_days: int
    low_confidence_threshold: float
    event_count: int = 0
    zero_result_count: int = 0
    zero_result_rate: float = 0.0
    low_confidence_count: int = 0
    low_confidence_rate: float = 0.0
    query_group_count: int = 0


class RetrievalQueryGroupResponse(BaseModel):
    kind: RetrievalAnalyticsGroupKind
    normalized_query: str
    event_count: int
    matching_count: int
    best_top_score: float | None
    surfaces: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    last_corpus_version_id: UUID | None


class RetrievalQueryGroupListResponse(BaseModel):
    window_days: int
    low_confidence_threshold: float
    items: list[RetrievalQueryGroupResponse]
    has_more: bool = False
