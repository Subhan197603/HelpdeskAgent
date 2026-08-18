"""Grammar parity and normalization tests for error-code extraction."""

from apps.api.app.knowledge.error_code_extraction import extract_error_codes
from apps.api.app.retrieval.fusion import _identifiers


def test_extraction_matches_the_fusion_identifier_grammar() -> None:
    text = "AP-810 invoice hold, ORA_600 crash, APEX4001 trace, plain words"
    assert extract_error_codes(text) == _identifiers(text)
    assert extract_error_codes(text) == frozenset({"AP-810", "ORA-600", "APEX4001"})


def test_extraction_normalizes_case_and_separators() -> None:
    assert extract_error_codes("ora-600 during ap 810 validation") == frozenset(
        {"ORA-600", "AP-810"}
    )
    assert extract_error_codes("ORA_600") == frozenset({"ORA-600"})


def test_extraction_merges_parts_and_skips_missing_ones() -> None:
    assert extract_error_codes("Fix AP-810 holds", None, "ORA-600 reference", None) == frozenset(
        {"AP-810", "ORA-600"}
    )
    assert extract_error_codes(None, None) == frozenset()
    assert extract_error_codes() == frozenset()


def test_extraction_respects_identifier_boundaries() -> None:
    assert extract_error_codes("XAP-810X is not a code") == frozenset()
    assert extract_error_codes("no codes in plain prose") == frozenset()
