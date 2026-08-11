"""Contract tests for configuration administration reads and the visibility toggle (Task 11.5C)."""

from typing import Any, cast

from fastapi.testclient import TestClient

from apps.api.app.admin.service import (
    summarize_rules,
    transition_action_types,
    transition_required_fields,
)
from apps.api.app.identity.authorization import ROLE_PERMISSIONS, Permission

WORKFLOWS_PATH = "/api/v1/admin/workflows"
WORKFLOW_DETAIL_PATH = "/api/v1/admin/workflows/{workflow_id}"
SLA_PATH = "/api/v1/admin/sla-policies"
SLA_DETAIL_PATH = "/api/v1/admin/sla-policies/{sla_definition_id}"
CALENDARS_PATH = "/api/v1/admin/calendars"
CALENDAR_DETAIL_PATH = "/api/v1/admin/calendars/{calendar_id}"
CATALOGUE_PATH = "/api/v1/admin/catalogue"
CATALOGUE_DETAIL_PATH = "/api/v1/admin/catalogue/{request_type_id}"
VISIBILITY_PATH = "/api/v1/admin/catalogue/{request_type_id}/visibility"

READ_OPERATIONS = (
    (WORKFLOWS_PATH, "get"),
    (WORKFLOW_DETAIL_PATH, "get"),
    (SLA_PATH, "get"),
    (SLA_DETAIL_PATH, "get"),
    (CALENDARS_PATH, "get"),
    (CALENDAR_DETAIL_PATH, "get"),
    (CATALOGUE_PATH, "get"),
    (CATALOGUE_DETAIL_PATH, "get"),
)

NEW_SCHEMAS = (
    "AdminWorkflowListResponse",
    "AdminWorkflowDetailResponse",
    "AdminWorkflowSummary",
    "AdminWorkflowStatusItem",
    "AdminWorkflowTransitionItem",
    "AdminSlaPolicyListResponse",
    "AdminSlaPolicyDetailResponse",
    "AdminSlaGoalItem",
    "AdminSlaCycleCounts",
    "AdminCalendarListResponse",
    "AdminCalendarDetailResponse",
    "AdminRequestTypeListResponse",
    "AdminRequestTypeDetailResponse",
    "AdminFormFieldItem",
    "AdminRequestTypeVisibilityRequest",
    "AdminRequestTypeVisibilityResponse",
)

_SAMPLE_ID = "6e0d8a1c-52a5-4b3f-9b34-8a4f0a4a2b10"


def _contract(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", client.get("/openapi.json").json())


def _schemas(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["components"]["schemas"])


def _operation(client: TestClient, path: str, method: str) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["paths"][path][method])


def test_config_endpoints_require_authentication(client: TestClient) -> None:
    responses = (
        client.get(WORKFLOWS_PATH),
        client.get(WORKFLOW_DETAIL_PATH.format(workflow_id=_SAMPLE_ID)),
        client.get(SLA_PATH),
        client.get(SLA_DETAIL_PATH.format(sla_definition_id=_SAMPLE_ID)),
        client.get(CALENDARS_PATH),
        client.get(CALENDAR_DETAIL_PATH.format(calendar_id=_SAMPLE_ID)),
        client.get(CATALOGUE_PATH),
        client.get(CATALOGUE_DETAIL_PATH.format(request_type_id=_SAMPLE_ID)),
        client.patch(
            VISIBILITY_PATH.format(request_type_id=_SAMPLE_ID),
            json={
                "active": True,
                "employee_visible": True,
                "expected_updated_at": "2030-01-01T00:00:00Z",
            },
        ),
    )
    for response in responses:
        assert response.status_code == 401


def test_config_contracts_document_error_statuses(client: TestClient) -> None:
    for path, method in READ_OPERATIONS:
        operation = _operation(client, path, method)
        responses = set(operation["responses"])
        assert {"401", "403", "422"} <= responses, f"{method} {path}"
        if "{" in path:
            assert "404" in responses, f"{method} {path}"
    visibility = _operation(client, VISIBILITY_PATH, "patch")
    assert {"401", "403", "404", "409", "422"} <= set(visibility["responses"])


def test_config_schemas_are_registered(client: TestClient) -> None:
    schemas = _schemas(client)
    for name in NEW_SCHEMAS:
        assert name in schemas, name


def test_visibility_contract_shapes(client: TestClient) -> None:
    schemas = _schemas(client)
    assert set(schemas["AdminRequestTypeVisibilityRequest"]["properties"]) == {
        "active",
        "employee_visible",
        "expected_updated_at",
    }
    assert set(schemas["AdminRequestTypeVisibilityResponse"]["properties"]) == {
        "request_type_id",
        "active_flag",
        "employee_visible_flag",
        "updated_at",
        "changed",
    }


def test_config_responses_expose_no_raw_rule_payloads(client: TestClient) -> None:
    """Rule JSON stays server-side: only summarized text lists are published."""
    schemas = _schemas(client)
    forbidden_fragments = (
        "_json",
        "condition_payload",
        "validator",
        "action_json",
        "form_schema",
        "secret",
        "token",
        "password",
        "credential",
    )
    for schema_name in NEW_SCHEMAS:
        for name in schemas[schema_name]["properties"]:
            lowered = name.lower()
            for fragment in forbidden_fragments:
                assert fragment not in lowered, f"{schema_name}.{name}"


def test_admin_config_permission_grants() -> None:
    for permission in (Permission.ADMIN_CONFIG_READ, Permission.ADMIN_CONFIG_WRITE):
        assert permission in ROLE_PERMISSIONS["PLATFORM_ADMIN"]
        for role_code in ROLE_PERMISSIONS:
            if role_code == "PLATFORM_ADMIN":
                continue
            assert permission not in ROLE_PERMISSIONS[role_code], (permission, role_code)


def test_rule_summaries_cover_seeded_shapes() -> None:
    assert summarize_rules(None) == []
    assert summarize_rules([]) == []
    assert summarize_rules({}) == []
    assert summarize_rules([{"status_code": "WAITING_FOR_CUSTOMER"}]) == [
        "Ticket status is WAITING_FOR_CUSTOMER"
    ]
    assert summarize_rules({"all": [{"field": "summary", "operator": "is_not_null"}]}) == [
        "summary is set"
    ]
    assert summarize_rules(
        {"all": [{"field": "work_type_code", "operator": "equals", "value": "ACCESS_REQUEST"}]}
    ) == ["work_type_code is ACCESS_REQUEST"]
    assert summarize_rules({"priority_code": "P1"}) == ["priority_code is P1"]
    assert summarize_rules(
        {
            "any": [
                {"field": "a", "operator": "equals", "value": 1},
                {"field": "b", "operator": "in", "value": [1, 2]},
            ]
        }
    ) == ["Any of the following:", "a is 1", "b is one of 1, 2"]
    assert summarize_rules({"unknown": {"nested": True}}) == ["Custom rule"]
    assert summarize_rules("garbage") == ["Custom rule"]


def test_transition_rule_extraction_covers_seeded_shapes() -> None:
    assert transition_required_fields([{"type": "required_field", "field": "resolution_code"}]) == [
        "resolution_code"
    ]
    assert transition_required_fields([{"type": "other"}]) == []
    assert transition_required_fields({"not": "a list"}) == []
    assert transition_action_types(
        [
            {"type": "SET_TIMESTAMP", "field": "resolved_at"},
            {"type": "APPROVAL_CONTINUATION"},
        ]
    ) == ["SET_TIMESTAMP", "APPROVAL_CONTINUATION"]
    assert transition_action_types([]) == []
