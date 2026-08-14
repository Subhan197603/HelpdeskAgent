"""Unit tests for restricted queue configuration and scoped pagination."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.queues.models import QueueDefinition, QueueTicket
from apps.api.app.queues.schemas import CannedResponseCreateRequest
from apps.api.app.queues.service import (
    QueueConfigurationError,
    QueueService,
    _compile_filter,
    _decode_cursor,
    _encode_cursor,
    _scope_hash,
)


def _queue(identifier: int = 1, *, visibility: str = "ALL_AGENTS") -> QueueDefinition:
    suffix = f"{identifier:012d}"
    return QueueDefinition(
        queue_id=UUID(f"37000000-0000-0000-0000-{suffix}"),
        queue_version_id=UUID(f"37100000-0000-0000-0000-{suffix}"),
        tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
        project_id=UUID("30000000-0000-0000-0000-000000000002"),
        project_code="ERP",
        name="Queue",
        description=None,
        filter_json={},
        sort_json=[{"field": "created_at", "direction": "DESC"}],
        columns_json=["ticket_key"],
        visibility_type=visibility,
        owner_group_id=UUID("23000000-0000-0000-0000-000000000002"),
        display_order=10,
    )


def _context() -> RequestContext:
    return RequestContext(
        tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
        user_id=UUID("22000000-0000-0000-0000-000000000004"),
        external_subject="agent",
        roles=frozenset({"AGENT"}),
        support_group_ids=frozenset({UUID("23000000-0000-0000-0000-000000000002")}),
        business_unit_id=None,
        correlation_id="00000000-0000-0000-0000-000000000001",
        request_id="queue-test",
    )


def test_restricted_filter_compiler_uses_only_fixed_sql_and_parameters() -> None:
    parameters: dict[str, object] = {}
    sql = _compile_filter(
        {
            "all": [
                {"field": "assignment_group_id", "operator": "is_not_null"},
                {"field": "priority_code", "operator": "in", "value": ["P1", "P2"]},
                {
                    "field": "assignee_user_id",
                    "operator": "equals_context",
                    "value": "user_id",
                },
            ]
        },
        parameters,
    )
    assert "ticket.assignment_group_id IS NOT NULL" in sql
    assert "ticket.priority_code" in sql
    assert ":queue_filter_0" in sql
    assert parameters == {"queue_filter_0": ["P1", "P2"]}


def test_canned_response_contract_is_bounded_plaintext_only() -> None:
    item = CannedResponseCreateRequest(name="Invoice reply", body="Please provide details.")
    assert item.body == "Please provide details."
    with pytest.raises(PydanticValidationError):
        CannedResponseCreateRequest.model_validate(
            {"name": "Unsafe", "body": "Text", "template": "{{ticket.id}}"}
        )
    with pytest.raises(PydanticValidationError):
        CannedResponseCreateRequest(name="Too large", body="x" * 10_001)


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "summary; DROP TABLE itsm.ticket", "operator": "equals", "value": "x"},
        {"field": "priority_code", "operator": "raw_sql", "value": "true"},
        {"all": []},
    ],
)
def test_restricted_filter_compiler_fails_closed(condition: object) -> None:
    with pytest.raises(QueueConfigurationError):
        _compile_filter(condition, {})


def test_queue_visibility_and_published_version_conflicts_fail_closed() -> None:
    service = object.__new__(QueueService)
    service._authorization = AuthorizationService()
    assert service._visible(_context(), _queue(visibility="GROUP"))
    hidden = replace(
        _queue(visibility="GROUP"),
        owner_group_id=UUID("23000000-0000-0000-0000-000000000099"),
    )
    assert not service._visible(_context(), hidden)
    with pytest.raises(QueueConfigurationError):
        service._effective([_queue(), replace(_queue(2), queue_id=_queue().queue_id)])


def test_cursor_is_stable_and_scoped_to_filters() -> None:
    ticket = QueueTicket(
        UUID("40000000-0000-0000-0000-000000000001"),
        "ERP-1",
        "Summary",
        "ERP",
        "P3",
        "NEW",
        "New",
        "Reporter",
        None,
        None,
        None,
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        None,
    )
    scope = _scope_hash(_queue().queue_id, search=None)
    cursor = _encode_cursor(ticket, scope)
    assert _decode_cursor(cursor, scope) == (ticket.created_at, ticket.ticket_id)
    with pytest.raises(ValidationError):
        _decode_cursor(cursor, _scope_hash(_queue().queue_id, search="changed"))
