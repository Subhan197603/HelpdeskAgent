"""Governed application of approved synonym expansions to retrieval queries.

The single retrieval-behavior change ratified for Milestone 15: when the
global switch is on and the tenant has opted in, approved registry entries
whose term appears whole-word in the normalized query append their bounded
expansions to the query. Two forms are produced because the lexical channel
uses websearch_to_tsquery, which ANDs plain words: the embedding input
appends expansions as plain words, while the lexical query joins each
expansion as an alternative phrase with "or" so expansion can only broaden,
never narrow, the lexical match. The original normalized query is always
preserved for the API response and query-event grouping, and any failure
falls back to the unexpanded query.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.retrieval.normalization import MAX_QUERY_CHARACTERS

MAX_APPENDED_EXPANSIONS = 5

_APPROVED_SQL = """
SELECT term,expansion FROM kb.retrieval_synonym
WHERE tenant_id=:tenant_id AND synonym_status='APPROVED'
ORDER BY term,expansion
"""


@dataclass(frozen=True)
class ExpandedQuery:
    search_query: str
    lexical_query: str
    applied: bool
    expanded_term_count: int


def expansion_tenant_ids(raw: str) -> frozenset[str]:
    return frozenset(value.strip().lower() for value in raw.split(",") if value.strip())


def expand_query(normalized_query: str, entries: list[tuple[str, str]]) -> ExpandedQuery:
    """Deterministically append approved expansions for whole-word term matches."""
    present_words = set(normalized_query.split(" "))
    padded = f" {normalized_query} "
    appended: list[str] = []
    for term, expansion in entries:
        if len(appended) >= MAX_APPENDED_EXPANSIONS:
            break
        if f" {term} " not in padded:
            continue
        if not set(expansion.split(" ")) - present_words:
            continue
        candidate = " ".join([normalized_query, *appended, expansion])
        if len(candidate) > MAX_QUERY_CHARACTERS:
            break
        if len(_lexical_query(normalized_query, [*appended, expansion])) > MAX_QUERY_CHARACTERS:
            break
        appended.append(expansion)
        present_words.update(expansion.split(" "))
    if not appended:
        return ExpandedQuery(normalized_query, normalized_query, False, 0)
    return ExpandedQuery(
        " ".join([normalized_query, *appended]),
        _lexical_query(normalized_query, appended),
        True,
        len(appended),
    )


def _lexical_query(normalized_query: str, expansions: list[str]) -> str:
    # websearch_to_tsquery ANDs plain words, so each expansion joins as an
    # alternative quoted phrase — expansion can only broaden the lexical match.
    alternatives = " or ".join(f'"{expansion}"' for expansion in expansions)
    return f"{normalized_query} or {alternatives}"


async def load_approved_entries(session: AsyncSession, tenant_id: UUID) -> list[tuple[str, str]]:
    rows = await session.execute(text(_APPROVED_SQL), {"tenant_id": tenant_id})
    return [(row.term, row.expansion) for row in rows]
