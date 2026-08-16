"""Knowledge-source contracts and fail-closed URL validation."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.ingestion.schemas import (
    ChangeReportPageResponse,
    ChangeReportSummary,
    RefreshRunCommand,
    SourceChangeReportResponse,
)
from apps.api.app.knowledge.models import KnowledgeSource
from apps.api.app.knowledge.schemas import RefreshLifecycleCommand, SourceCreate
from apps.api.app.knowledge.service import _REFRESH_TRANSITIONS, _canonical, _response

OWNER = UUID("22000000-0000-0000-0000-000000000007")
TENANT = UUID("20000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _source(**overrides: object) -> SourceCreate:
    values: dict[str, object] = {
        "code": "POLICY_SOURCE",
        "name": "Policy source",
        "source_type": "COMPANY_POLICY",
        "canonical_location": "repository:knowledge/policy",
        "acquisition_method": "MANUAL_UPLOAD",
        "audience_scope": "EMPLOYEE",
        "owner_user_id": OWNER,
    }
    values.update(overrides)
    return SourceCreate.model_validate(values)


@pytest.mark.parametrize("audience", ["EMPLOYEE", "ANALYST", "RESTRICTED", "ADMINISTRATIVE"])
def test_all_governed_audiences_are_explicit(audience: str) -> None:
    assert _source(audience_scope=audience).audience_scope == audience


@pytest.mark.parametrize("status", ["ACTIVE", "DISABLED", "RETIRED"])
def test_all_source_lifecycle_states_are_explicit(status: str) -> None:
    assert _source(status=status).status == status


def test_source_requires_an_owner_and_distinct_product_module() -> None:
    with pytest.raises(PydanticValidationError, match="source owner"):
        _source(owner_user_id=None)
    node = UUID("24000000-0000-0000-0000-000000000001")
    with pytest.raises(PydanticValidationError, match="must be different"):
        _source(product_node_id=node, module_node_id=node)


@pytest.mark.parametrize(
    "location",
    [
        "http://example.invalid/file",
        "https://user:secret@example.invalid/file",
        "https://example.invalid/file?token=secret",
        "https://example.invalid/file#fragment",
    ],
)
def test_external_canonical_locations_fail_closed(location: str) -> None:
    source = _source(
        source_type="OTHER_EXTERNAL",
        acquisition_method="APPROVED_DIRECT_DOWNLOAD",
        canonical_location=location,
    )
    with pytest.raises(ValidationError):
        _canonical(source)


def test_external_canonical_location_is_normalized_without_query_material() -> None:
    source = _source(
        source_type="OTHER_EXTERNAL",
        acquisition_method="APPROVED_DIRECT_DOWNLOAD",
        canonical_location="HTTPS://DOCS.EXAMPLE.INVALID/policy",
    )
    assert _canonical(source) == "https://docs.example.invalid/policy"


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (
            "KNOWLEDGE_AUTHOR",
            Permission.KNOWLEDGE_SOURCE_UPDATE,
            Permission.KNOWLEDGE_SOURCE_APPROVE,
        ),
        (
            "KNOWLEDGE_APPROVER",
            Permission.KNOWLEDGE_SOURCE_APPROVE,
            Permission.KNOWLEDGE_SOURCE_UPDATE,
        ),
        (
            "CUSTOMER",
            Permission.CATALOG_SERVICE_READ,
            Permission.KNOWLEDGE_SOURCE_READ_ADMIN,
        ),
    ],
)
def test_source_administration_roles_are_separated(
    role: str, allowed: Permission, denied: Permission
) -> None:
    context = RequestContext(
        tenant_id=TENANT,
        user_id=OWNER,
        external_subject="knowledge-role-test",
        roles=frozenset({role}),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id=str(TENANT),
        request_id="knowledge-role-test",
    )
    authorization = AuthorizationService()
    assert authorization.is_allowed(context, allowed)
    assert not authorization.is_allowed(context, denied)


def _knowledge_source(
    *, source_status: str = "ACTIVE", refresh_state: str = "CURRENT"
) -> KnowledgeSource:
    return KnowledgeSource(
        UUID("25000000-0000-0000-0000-000000000001"),
        TENANT,
        "POLICIES",
        "Policies",
        "COMPANY_POLICY",
        None,
        "repository:knowledge/policy",
        "MANUAL_UPLOAD",
        False,
        None,
        "EMPLOYEE",
        source_status,
        "APPROVED",
        OWNER,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "en",
        None,
        NOW,
        1,
        NOW,
        NOW,
        refresh_state,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def test_refresh_due_date_is_only_accepted_with_mark_refresh_due() -> None:
    command = RefreshLifecycleCommand.model_validate(
        {"action": "MARK_REFRESH_DUE", "expected_version": 1, "refresh_due_at": NOW}
    )
    assert command.refresh_due_at == NOW
    with pytest.raises(PydanticValidationError, match="MARK_REFRESH_DUE"):
        RefreshLifecycleCommand.model_validate(
            {"action": "MARK_CURRENT", "expected_version": 1, "refresh_due_at": NOW}
        )


def test_refresh_transitions_are_deterministic_and_never_enter_refreshing() -> None:
    assert set(_REFRESH_TRANSITIONS) == {"MARK_REFRESH_DUE", "MARK_CURRENT", "MARK_STALE"}
    for action, (target, allowed_from) in _REFRESH_TRANSITIONS.items():
        assert target != "REFRESHING"
        assert target not in allowed_from, action
        assert allowed_from <= {"CURRENT", "REFRESH_DUE", "STALE"}


@pytest.mark.parametrize(
    ("source_status", "refresh_state", "effective"),
    [
        ("ACTIVE", "CURRENT", "CURRENT"),
        ("ACTIVE", "REFRESH_DUE", "REFRESH_DUE"),
        ("DISABLED", "STALE", "STALE"),
        ("RETIRED", "CURRENT", "RETIRED"),
        ("RETIRED", "REFRESH_DUE", "RETIRED"),
    ],
)
def test_effective_refresh_state_derives_retired_from_source_status(
    source_status: str, refresh_state: str, effective: str
) -> None:
    response = _response(
        _knowledge_source(source_status=source_status, refresh_state=refresh_state)
    )
    assert response.effective_refresh_state == effective


def test_refresh_run_command_requires_a_positive_expected_version() -> None:
    assert RefreshRunCommand.model_validate({"expected_version": 3}).expected_version == 3
    with pytest.raises(PydanticValidationError):
        RefreshRunCommand.model_validate({"expected_version": 0})


def test_change_report_summarizes_every_classification_deterministically() -> None:
    pages = [
        ChangeReportPageResponse(
            item_id=UUID(f"29000000-0000-0000-0000-00000000000{index}"),
            manifest_key=f"page-{index}",
            document_title=f"Page {index}",
            status=status,
            classification=classification,
            previous_sha256=None,
            observed_sha256=None,
            redirect_target_url=None,
            observed_http_status=None,
            error_code=None,
            final_failure=final_failure,
            completed_at=None,
        )
        for index, (status, classification, final_failure) in enumerate(
            [
                ("SKIPPED_UNCHANGED", "UNCHANGED", False),
                ("ACQUIRED", "CHANGED", False),
                ("SKIPPED_REMOVED", "REMOVED", False),
                ("SKIPPED_REDIRECTED", "REDIRECTED", False),
                ("FAILED", None, True),
            ]
        )
    ]
    report = SourceChangeReportResponse(
        source_id=UUID("25000000-0000-0000-0000-000000000001"),
        run_id=None,
        run_status=None,
        requested_by=None,
        created_at=None,
        completed_at=None,
        summary=ChangeReportSummary(
            unchanged=sum(1 for page in pages if page.classification == "UNCHANGED"),
            changed=sum(1 for page in pages if page.classification == "CHANGED"),
            removed=sum(1 for page in pages if page.classification == "REMOVED"),
            redirected=sum(1 for page in pages if page.classification == "REDIRECTED"),
            failed=sum(1 for page in pages if page.final_failure),
        ),
        pages=pages,
    )
    assert report.summary.model_dump() == {
        "unchanged": 1,
        "changed": 1,
        "removed": 1,
        "redirected": 1,
        "failed": 1,
    }
