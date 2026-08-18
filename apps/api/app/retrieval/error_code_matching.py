"""Governed exact error-code candidate matching for retrieval queries.

The single retrieval-behavior change ratified for Milestone 16: when the
global switch is on and the tenant has opted in, published chunks indexed
under an error code that appears in the normalized query join the candidate
set. Matching only broadens candidate selection — the added candidates are
ranked by the unchanged fusion formula, where the existing exact-identifier
boost applies to them by construction. The original normalized query is
always preserved, and any failure falls back to the unmatched candidate set.
"""

from dataclasses import dataclass

from apps.api.app.retrieval.fusion import _identifiers
from apps.api.app.retrieval.models import RetrievalCandidate


@dataclass(frozen=True)
class ErrorCodeMatch:
    applied: bool
    matched_error_code_count: int
    candidates: tuple[RetrievalCandidate, ...]


UNMATCHED = ErrorCodeMatch(False, 0, ())


def matching_tenant_ids(raw: str) -> frozenset[str]:
    return frozenset(value.strip().lower() for value in raw.split(",") if value.strip())


def query_error_codes(normalized_query: str) -> tuple[str, ...]:
    """Extract the query's error codes with the shared fusion grammar."""
    return tuple(sorted(_identifiers(normalized_query)))


def matched_error_code_count(
    candidates: tuple[RetrievalCandidate, ...], error_codes: tuple[str, ...]
) -> int:
    """Count the distinct query codes evidenced by the matched candidates."""
    codes = frozenset(error_codes)
    matched: set[str] = set()
    for candidate in candidates:
        matched |= codes & _identifiers(
            " ".join(
                part
                for part in (
                    candidate.document_title,
                    candidate.heading_path,
                    candidate.section_title,
                    candidate.content_text,
                )
                if part
            )
        )
    return len(matched)
