"""Bounded Unicode query normalization shared by lexical and vector retrieval."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
MAX_QUERY_CHARACTERS = 500


class InvalidRetrievalQuery(ValueError):
    """A retrieval query cannot be safely normalized."""


def normalize_query(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf"} or character.isspace()
    )
    normalized = _WHITESPACE.sub(" ", normalized).strip().casefold()
    if not normalized:
        raise InvalidRetrievalQuery("Retrieval query is empty")
    if len(normalized) > MAX_QUERY_CHARACTERS:
        raise InvalidRetrievalQuery("Retrieval query exceeds the character limit")
    return normalized
