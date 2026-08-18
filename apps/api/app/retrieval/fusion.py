"""Deterministic score normalization, fusion, boosts, and evidence shaping."""

import re
from collections import defaultdict
from dataclasses import replace
from uuid import UUID

from apps.api.app.retrieval.models import (
    RetrievalCandidate,
    RetrievalConfiguration,
    RetrievalEvidence,
    RetrievalFilters,
    ScoreComponents,
)

_IDENTIFIER = re.compile(
    r"(?<![A-Z0-9])(?:[A-Z]{2,12}[-_ ]\d{2,12}|[A-Z]{3,12}\d{3,12})(?![A-Z0-9])"
)


def fuse_candidates(
    query: str,
    lexical: tuple[RetrievalCandidate, ...],
    vector: tuple[RetrievalCandidate, ...],
    filters: RetrievalFilters,
    configuration: RetrievalConfiguration,
    rerank_scores: dict[UUID, float] | None = None,
    *,
    error_code_matches: tuple[RetrievalCandidate, ...] = (),
    limit: int,
) -> tuple[RetrievalEvidence, ...]:
    lexical_scores = _normalized(lexical)
    vector_scores = _normalized(vector)
    # Governed error-code matches only broaden the candidate set: without a
    # lexical or vector rank they score through the unchanged formula as
    # boosts alone, and duplicates collapse onto the ranked channels.
    candidates = {
        candidate.chunk_id: candidate for candidate in (*error_code_matches, *lexical, *vector)
    }
    ranks: dict[UUID, dict[str, int]] = defaultdict(dict)
    for candidate in lexical:
        ranks[candidate.chunk_id]["lexical"] = candidate.rank
    for candidate in vector:
        ranks[candidate.chunk_id]["vector"] = candidate.rank

    maximum_fusion = (configuration.lexical_weight + configuration.vector_weight) / (
        configuration.rrf_k + 1
    )
    identifiers = _identifiers(query)
    results: list[RetrievalEvidence] = []
    for chunk_id, candidate in candidates.items():
        chunk_ranks = ranks[chunk_id]
        fusion = (
            configuration.lexical_weight / (configuration.rrf_k + chunk_ranks["lexical"])
            if "lexical" in chunk_ranks
            else 0.0
        ) + (
            configuration.vector_weight / (configuration.rrf_k + chunk_ranks["vector"])
            if "vector" in chunk_ranks
            else 0.0
        )
        fusion = fusion / maximum_fusion if maximum_fusion else 0.0
        identifier_boost = (
            configuration.exact_identifier_boost
            if identifiers
            & _identifiers(
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
            else 0.0
        )
        metadata_boost = configuration.metadata_boost * _metadata_matches(candidate, filters)
        authority_boost = configuration.source_authority_weights.get(candidate.source_type, 0.0)
        rerank = (rerank_scores or {}).get(chunk_id)
        base = fusion + identifier_boost + metadata_boost + authority_boost
        final = (
            (1 - configuration.rerank_weight) * base + configuration.rerank_weight * rerank
            if rerank is not None
            else base
        )
        results.append(
            RetrievalEvidence(
                rank=0,
                chunk_id=chunk_id,
                document_id=candidate.document_id,
                document_version_id=candidate.document_version_id,
                source_id=candidate.source_id,
                document_title=candidate.document_title,
                heading_path=candidate.heading_path,
                section_title=candidate.section_title,
                section_anchor=candidate.section_anchor,
                content_text=candidate.content_text,
                language_code=candidate.language_code,
                release_family=candidate.release_family,
                release_code=candidate.release_code,
                product_code=candidate.product_code,
                product_name=candidate.product_name,
                module_code=candidate.module_code,
                module_name=candidate.module_name,
                source_type=candidate.source_type,
                canonical_uri=candidate.canonical_uri,
                page_number=candidate.page_number,
                score=final,
                components=ScoreComponents(
                    lexical=lexical_scores.get(chunk_id),
                    vector=vector_scores.get(chunk_id),
                    fusion=fusion,
                    exact_identifier_boost=identifier_boost,
                    metadata_boost=metadata_boost,
                    source_authority_boost=authority_boost,
                    rerank=rerank,
                ),
                document_type=candidate.document_type,
            )
        )
    ordered = sorted(results, key=lambda item: (-item.score, str(item.chunk_id)))[:limit]
    return tuple(replace(item, rank=rank) for rank, item in enumerate(ordered, start=1))


def _normalized(candidates: tuple[RetrievalCandidate, ...]) -> dict[UUID, float]:
    if not candidates:
        return {}
    minimum = min(candidate.score for candidate in candidates)
    maximum = max(candidate.score for candidate in candidates)
    if maximum == minimum:
        return {candidate.chunk_id: 1.0 for candidate in candidates}
    return {
        candidate.chunk_id: (candidate.score - minimum) / (maximum - minimum)
        for candidate in candidates
    }


def _identifiers(value: str) -> frozenset[str]:
    return frozenset(
        match.group(0).replace(" ", "-").replace("_", "-")
        for match in _IDENTIFIER.finditer(value.upper())
    )


def _metadata_matches(candidate: RetrievalCandidate, filters: RetrievalFilters) -> int:
    matches = 0
    if filters.product_codes and candidate.product_code in filters.product_codes:
        matches += 1
    if filters.module_codes and candidate.module_code in filters.module_codes:
        matches += 1
    if filters.release_families and candidate.release_family in filters.release_families:
        matches += 1
    if filters.release_codes and candidate.release_code in filters.release_codes:
        matches += 1
    return matches
