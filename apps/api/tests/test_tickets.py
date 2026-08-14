"""Ticket form normalization, authorization, and API contract tests."""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.app.catalog.models import FormFieldRecord
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.tickets.schemas import CustomFieldInput
from apps.api.app.tickets.service import TicketMetrics
from apps.api.app.tickets.validation import validate_and_normalize

from .test_identity import identity


def _field(
    code: str,
    data_type: str,
    *,
    required: bool = False,
    validation: dict[str, Any] | None = None,
    option: str | None = None,
    active_condition: dict[str, Any] | None = None,
) -> FormFieldRecord:
    return FormFieldRecord(
        UUID(int=len(code)),
        code,
        code.title(),
        data_type,
        None,
        None,
        10,
        required,
        None,
        validation or {},
        active_condition or {},
        UUID(int=100 + len(code)) if option else None,
        option,
        option,
        10 if option else None,
    )


def test_form_validation_normalizes_supported_values() -> None:
    fields = [
        _field("title", "TEXT", required=True, validation={"minimum_length": 3}),
        _field("count", "NUMBER", validation={"minimum": 1, "maximum": 5}),
        _field("enabled", "BOOLEAN"),
        _field("tags", "MULTI_SELECT", option="B"),
        _field("tags", "MULTI_SELECT", option="A"),
    ]
    result = validate_and_normalize(
        fields,
        [
            CustomFieldInput(field_code="title", value="  A   title "),
            CustomFieldInput(field_code="count", value="2.0"),
            CustomFieldInput(field_code="enabled", value="true"),
            CustomFieldInput(field_code="tags", value=["B", "A"]),
        ],
    )
    assert result == {"title": "A title", "count": "2", "enabled": True, "tags": ["A", "B"]}


@pytest.mark.parametrize(
    "supplied,error_key",
    [
        ([CustomFieldInput(field_code="unknown", value="x")], "custom_fields.unknown"),
        ([CustomFieldInput(field_code="title", value="a")], "custom_fields.title"),
        ([CustomFieldInput(field_code="choice", value="INACTIVE")], "custom_fields.choice"),
    ],
)
def test_form_validation_rejects_unknown_short_and_inactive_values(
    supplied: list[CustomFieldInput], error_key: str
) -> None:
    fields = [
        _field("title", "TEXT", required=True, validation={"minimum_length": 3}),
        _field("choice", "SINGLE_SELECT", option="ACTIVE"),
    ]
    with pytest.raises(ValidationError) as caught:
        validate_and_normalize(fields, supplied)
    assert caught.value.field_errors is not None and error_key in caught.value.field_errors


def test_form_validation_rejects_duplicates_and_numeric_range() -> None:
    fields = [_field("amount", "NUMBER", validation={"minimum": 1, "maximum": 5})]
    with pytest.raises(ValidationError) as duplicate:
        validate_and_normalize(
            fields,
            [
                CustomFieldInput(field_code="amount", value=2),
                CustomFieldInput(field_code="amount", value=3),
            ],
        )
    assert duplicate.value.field_errors
    with pytest.raises(ValidationError) as ranged:
        validate_and_normalize(fields, [CustomFieldInput(field_code="amount", value=9)])
    assert ranged.value.field_errors
    with pytest.raises(ValidationError) as non_finite:
        validate_and_normalize(fields, [CustomFieldInput(field_code="amount", value="NaN")])
    assert non_finite.value.field_errors


def test_ticket_permissions_require_recognized_authenticated_role() -> None:
    authorization = AuthorizationService()
    assert authorization.is_allowed(identity().context, Permission.TICKET_DRAFT_CREATE)
    assert not authorization.is_allowed(
        identity(roles=frozenset()).context, Permission.TICKET_DRAFT_CREATE
    )


def test_ticket_openapi_covers_the_complete_task_surface(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/v1/ticket-drafts",
        "/api/v1/ticket-drafts/{draft_id}",
        "/api/v1/ticket-drafts/{draft_id}/validate",
        "/api/v1/ticket-drafts/{draft_id}/submit",
        "/api/v1/tickets/{ticket_key}",
        "/api/v1/my/tickets",
        "/api/v1/agent/watched-tickets",
        "/api/v1/agent/tickets/{ticket_key}/watch",
    } <= paths.keys()
    assert "Idempotency-Key" in {
        parameter["name"]
        for parameter in paths["/api/v1/ticket-drafts/{draft_id}/submit"]["post"]["parameters"]
    }


def test_watchlist_contract_has_no_client_controlled_ownership_fields(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["WatchStateResponse"]["properties"]) == {"watched", "watched_at"}
    assert {"items", "limit", "next_cursor"} == set(schemas["WatchedTicketPage"]["properties"])
    assert "tenant_id" not in schemas["WatchedTicketResponse"]["properties"]
    assert "owner_user_id" not in schemas["WatchedTicketResponse"]["properties"]


def test_ticket_metrics_record_operations_without_request_content() -> None:
    metrics = TicketMetrics()
    metrics.record("create_draft", 0.0)
    assert metrics.operation_counts == {"create_draft": 1}
    assert metrics.operation_duration_ms_total > 0
