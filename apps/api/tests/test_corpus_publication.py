"""Corpus publication contracts, blockers, and deterministic responses."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from apps.api.app.core.exceptions import ConflictError
from apps.api.app.knowledge.corpus_publication_models import (
    CorpusPublicationEvent,
    CorpusVersion,
    PublicationReadiness,
)
from apps.api.app.knowledge.corpus_publication_service import (
    _blockers,
    _event_response,
    _readiness_response,
    _version_response,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = UUID("20000000-0000-0000-0000-000000000001")
RUN_ID = UUID("30000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("40000000-0000-0000-0000-000000000001")
ACTOR = UUID("22000000-0000-0000-0000-000000000007")


def _version(**overrides: object) -> CorpusVersion:
    values: dict[str, object] = {
        "corpus_version_id": VERSION_ID,
        "tenant_id": TENANT,
        "version_number": 3,
        "validation_run_id": RUN_ID,
        "published_by": ACTOR,
        "published_at": NOW,
        "document_count": 12,
        "chunk_count": 42,
        "suppressed_chunk_count": 2,
        "active_flag": True,
        "row_version": 1,
        "created_at": NOW,
    }
    values.update(overrides)
    return CorpusVersion(**values)  # type: ignore[arg-type]


def _readiness(**overrides: object) -> PublicationReadiness:
    values: dict[str, object] = {
        "validation_run_id": RUN_ID,
        "run_completed": True,
        "truncated": False,
        "stale": False,
        "suppression_flagged_chunks": 2,
    }
    values.update(overrides)
    return PublicationReadiness(**values)  # type: ignore[arg-type]


def test_ready_corpus_has_no_blockers_and_is_publishable() -> None:
    response = _readiness_response(_readiness())
    assert response.publishable is True
    assert response.blockers == []
    assert response.validation_run_id == RUN_ID
    assert response.suppression_flagged_chunks == 2


def test_missing_validation_run_blocks_publication() -> None:
    assert _blockers(_readiness(validation_run_id=None)) == ["NO_VALIDATION_RUN"]


def test_incomplete_truncated_and_stale_runs_block_publication() -> None:
    blockers = _blockers(_readiness(run_completed=False, truncated=True, stale=True))
    assert blockers == [
        "VALIDATION_RUN_INCOMPLETE",
        "VALIDATION_RUN_TRUNCATED",
        "VALIDATION_STALE",
    ]
    assert _readiness_response(_readiness(stale=True)).publishable is False


def test_version_response_reports_active_state_and_counts() -> None:
    response = _version_response(_version(), replayed=True)
    assert response.id == VERSION_ID
    assert response.version_number == 3
    assert response.active is True
    assert response.replayed is True
    assert response.suppressed_chunk_count == 2


def test_event_response_maps_actions_and_fails_closed() -> None:
    event = CorpusPublicationEvent(
        publication_event_id=UUID("50000000-0000-0000-0000-000000000001"),
        action_code="ROLLED_BACK",
        corpus_version_number=2,
        previous_corpus_version_number=3,
        actor_user_id=ACTOR,
        evidence_json={"restored_version_number": 2},
        occurred_at=NOW,
    )
    response = _event_response(event)
    assert response.action == "ROLLED_BACK"
    assert response.previous_corpus_version_number == 3
    with pytest.raises(ConflictError):
        _event_response(
            CorpusPublicationEvent(
                publication_event_id=UUID("50000000-0000-0000-0000-000000000002"),
                action_code="RETIRED",
                corpus_version_number=1,
                previous_corpus_version_number=None,
                actor_user_id=ACTOR,
                evidence_json={},
                occurred_at=NOW,
            )
        )
