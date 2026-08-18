"""Deterministic error-code extraction shared with the fusion identifier grammar."""

from apps.api.app.retrieval.fusion import _identifiers


def extract_error_codes(*parts: str | None) -> frozenset[str]:
    """Extract normalized error-code identifiers from the given text parts.

    Delegates to the fusion identifier grammar so indexed codes always agree
    with the identifiers the fusion boost recognizes in queries and
    candidates.
    """
    return _identifiers(" ".join(part for part in parts if part))
