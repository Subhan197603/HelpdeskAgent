"""Corpus validation contracts and deterministic report assembly."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from apps.api.app.core.exceptions import ConflictError
from apps.api.app.knowledge.corpus_validation_models import (
    CorpusValidationFinding,
    CorpusValidationRun,
)
from apps.api.app.knowledge.corpus_validation_service import (
    NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
    _empty_report,
    _finding_type,
    _report,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = UUID("20000000-0000-0000-0000-000000000001")
RUN_ID = UUID("30000000-0000-0000-0000-000000000001")


def _run(**overrides: object) -> CorpusValidationRun:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "tenant_id": TENANT,
        "run_status": "COMPLETED",
        "requested_by": UUID("22000000-0000-0000-0000-000000000007"),
        "similarity_threshold": Decimal("0.950"),
        "document_count": 4,
        "chunk_count": 9,
        "structural_defect_count": 1,
        "empty_chunk_count": 1,
        "duplicate_document_count": 2,
        "near_duplicate_chunk_count": 1,
        "truncated_flag": False,
        "started_at": NOW,
        "completed_at": NOW,
        "created_at": NOW,
        "row_version": 2,
    }
    values.update(overrides)
    return CorpusValidationRun(**values)  # type: ignore[arg-type]


def test_similarity_threshold_is_a_recorded_constant() -> None:
    assert NEAR_DUPLICATE_SIMILARITY_THRESHOLD == 0.95


def test_report_assembles_summary_and_findings_deterministically() -> None:
    finding = CorpusValidationFinding(
        finding_id=UUID("31000000-0000-0000-0000-000000000001"),
        finding_type="NEAR_DUPLICATE_CHUNK",
        document_id=UUID("32000000-0000-0000-0000-000000000001"),
        document_title="Handbook",
        document_version_id=None,
        chunk_id=UUID("33000000-0000-0000-0000-000000000001"),
        counterpart_document_id=UUID("32000000-0000-0000-0000-000000000002"),
        counterpart_document_title="Handbook copy",
        counterpart_chunk_id=UUID("33000000-0000-0000-0000-000000000002"),
        duplicate_group_key="abc123",
        similarity_score=Decimal("0.9876"),
        suppression_flagged=True,
        evidence_json={"similarity": 0.9876},
    )
    report = _report(_run(), [finding], replayed=True)
    assert report.run_id == RUN_ID
    assert report.status == "COMPLETED"
    assert report.similarity_threshold == 0.95
    assert report.replayed is True
    assert report.summary.model_dump() == {
        "structural_defects": 1,
        "empty_chunks": 1,
        "duplicate_documents": 2,
        "near_duplicate_chunks": 1,
    }
    assert report.findings[0].similarity_score == 0.9876
    assert report.findings[0].suppression_flagged is True


def test_empty_report_has_no_run_and_zero_counts() -> None:
    report = _empty_report()
    assert report.run_id is None
    assert report.status is None
    assert report.findings == []
    assert report.summary.model_dump() == {
        "structural_defects": 0,
        "empty_chunks": 0,
        "duplicate_documents": 0,
        "near_duplicate_chunks": 0,
    }


def test_unknown_finding_type_fails_closed() -> None:
    with pytest.raises(ConflictError):
        _finding_type("SOMETHING_ELSE")
    assert _finding_type("DUPLICATE_DOCUMENT") == "DUPLICATE_DOCUMENT"
