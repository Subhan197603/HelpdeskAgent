"""Deterministic validation before a processing version may be published."""

from dataclasses import dataclass

from ingestion.chunkers import Chunk
from ingestion.parsers import ParsedDocument


@dataclass(frozen=True, slots=True)
class ValidationContext:
    expected_language: str
    release_valid: bool
    product_valid: bool
    source_permission_valid: bool
    document_approval_status: str
    canonical_url: str | None
    copyright_notice: str | None
    embedded_count: int


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: str
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: dict[str, float | int]


def validate_corpus(
    parsed: ParsedDocument, chunks: tuple[Chunk, ...], context: ValidationContext
) -> ValidationResult:
    failures: list[str] = []
    warnings: list[str] = []
    normalized = parsed.normalized_text
    if not normalized.strip():
        failures.append("EMPTY_EXTRACTION")
    if not chunks:
        failures.append("NO_CHUNKS")
    if context.embedded_count != len(chunks):
        failures.append("INCOMPLETE_EMBEDDINGS")
    if not context.release_valid:
        failures.append("INVALID_RELEASE")
    if not context.product_valid:
        failures.append("INVALID_PRODUCT_MODULE")
    if not context.source_permission_valid:
        failures.append("INVALID_SOURCE_PERMISSION")
    broken_ratio = normalized.count("\ufffd") / max(1, len(normalized))
    if broken_ratio > 0.001:
        failures.append("BROKEN_CHARACTER_RATIO")
    duplicate_ratio = 1.0 - (len({chunk.content_hash for chunk in chunks}) / max(1, len(chunks)))
    if duplicate_ratio > 0.2:
        warnings.append("HIGH_DUPLICATE_RATIO")
    if context.document_approval_status != "APPROVED":
        warnings.append("DOCUMENT_NOT_APPROVED")
    if not context.canonical_url:
        warnings.append("CANONICAL_URL_MISSING")
    if not context.copyright_notice:
        warnings.append("COPYRIGHT_NOTICE_MISSING")
    if context.expected_language.lower().split("-", 1)[0] != "en":
        warnings.append("LANGUAGE_REQUIRES_REVIEW")
    heading_count = sum(bool(chunk.heading_path) for chunk in chunks)
    if chunks and heading_count == 0:
        warnings.append("HEADINGS_MISSING")
    sizes = [chunk.token_count for chunk in chunks]
    metrics: dict[str, float | int] = {
        "chunk_count": len(chunks),
        "embedded_chunk_count": context.embedded_count,
        "average_chunk_tokens": sum(sizes) / max(1, len(sizes)),
        "maximum_chunk_tokens": max(sizes, default=0),
        "duplicate_ratio": duplicate_ratio,
        "broken_character_ratio": broken_ratio,
        "table_section_count": sum(
            section.table_markdown is not None for section in parsed.sections
        ),
        "heading_chunk_count": heading_count,
    }
    status = "FAILED" if failures else "WARNING" if warnings else "PASSED"
    return ValidationResult(status, tuple(failures), tuple(warnings), metrics)
