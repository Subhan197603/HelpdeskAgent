"""Unit tests for deterministic routing inputs and rule ordering."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.core.rules import evaluate
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.routing.models import RoutingRuleVersion, RoutingTicket
from apps.api.app.routing.service import (
    RoutingConfigurationError,
    RoutingService,
    _routing_values,
)


def _ticket() -> RoutingTicket:
    return RoutingTicket(
        ticket_id=UUID("40000000-0000-0000-0000-000000000001"),
        tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
        ticket_key="ERP-1",
        project_id=UUID("30000000-0000-0000-0000-000000000002"),
        project_code="ERP",
        service_node_id=UUID("31000000-0000-0000-0000-000000000005"),
        service_node_code="ACCOUNTS_PAYABLE",
        service_code="ERP",
        module_code="ACCOUNTS_PAYABLE",
        environment_code="PROD",
        work_type_code="INCIDENT",
        priority_code="P4",
        status_code="NEW",
        summary="Invoice validation failure",
        description="A payable invoice cannot be validated.",
        assignment_group_id=None,
        assignee_user_id=None,
        row_version=1,
        custom_fields={"affected_ledger": "UK01"},
    )


def _rule(
    identifier: int,
    priority: int,
    condition: object,
    effective: datetime,
) -> RoutingRuleVersion:
    suffix = f"{identifier:012d}"
    return RoutingRuleVersion(
        routing_rule_id=UUID(f"36000000-0000-0000-0000-{suffix}"),
        routing_rule_version_id=UUID(f"36100000-0000-0000-0000-{suffix}"),
        version_number=1,
        rule_priority=priority,
        condition=condition,
        assignment_group_id=UUID("23000000-0000-0000-0000-000000000002"),
        assignment_method="GROUP_ONLY",
        assignee_user_id=None,
        effective_from=effective,
        group_code=f"GROUP_{identifier}",
    )


def test_routing_exposes_every_supported_predicate_dimension() -> None:
    values = _routing_values(_ticket())
    assert evaluate(
        {
            "all": [
                {"field": "project_code", "operator": "equals", "value": "ERP"},
                {"field": "service_code", "operator": "equals", "value": "ERP"},
                {
                    "field": "module_code",
                    "operator": "equals",
                    "value": "ACCOUNTS_PAYABLE",
                },
                {"field": "environment_code", "operator": "equals", "value": "PROD"},
                {"field": "work_type_code", "operator": "equals", "value": "INCIDENT"},
                {"field": "priority_code", "operator": "equals", "value": "P4"},
                {"field": "field.affected_ledger", "operator": "equals", "value": "UK01"},
            ]
        },
        values,
    )


def test_rule_order_uses_priority_specificity_effective_date_and_stable_id() -> None:
    service = object.__new__(RoutingService)
    old = datetime(2025, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 1, 1, tzinfo=UTC)
    broad = _rule(
        4,
        20,
        {"field": "project_code", "operator": "equals", "value": "ERP"},
        recent,
    )
    specific_old = _rule(
        3,
        20,
        {
            "all": [
                {"field": "project_code", "operator": "equals", "value": "ERP"},
                {
                    "field": "module_code",
                    "operator": "equals",
                    "value": "ACCOUNTS_PAYABLE",
                },
            ]
        },
        old,
    )
    specific_recent_high_id = _rule(2, 20, specific_old.condition, recent)
    specific_recent_low_id = _rule(1, 20, specific_old.condition, recent)
    lower_precedence = _rule(5, 30, specific_old.condition, recent)
    default = _rule(99, 9999, {}, old)
    selected, fallback, evaluated = service._select_rule(
        [
            lower_precedence,
            broad,
            specific_old,
            specific_recent_high_id,
            specific_recent_low_id,
            default,
        ],
        _ticket(),
    )
    assert selected.routing_rule_version_id == specific_recent_low_id.routing_rule_version_id
    assert fallback is False
    assert evaluated == [
        {
            "routing_rule_version_id": str(specific_recent_low_id.routing_rule_version_id),
            "matched": True,
        }
    ]


def test_explicit_default_is_used_when_no_rule_matches() -> None:
    service = object.__new__(RoutingService)
    effective = datetime(2025, 1, 1, tzinfo=UTC)
    unmatched = _rule(
        1,
        10,
        {"field": "project_code", "operator": "equals", "value": "HCM"},
        effective,
    )
    default = _rule(2, 9999, {}, effective)
    selected, fallback, evaluated = service._select_rule([unmatched, default], _ticket())
    assert selected == default
    assert fallback is True
    assert [item["matched"] for item in evaluated] == [False, True]


def test_overlapping_published_versions_and_missing_default_fail_closed() -> None:
    service = object.__new__(RoutingService)
    effective = datetime(2025, 1, 1, tzinfo=UTC)
    rule = _rule(1, 10, {"field": "project_code", "operator": "equals", "value": "ERP"}, effective)
    overlapping = replace(
        rule,
        routing_rule_version_id=UUID("36100000-0000-0000-0000-000000000009"),
        version_number=2,
    )
    default = _rule(2, 9999, {}, effective)
    with pytest.raises(RoutingConfigurationError):
        service._select_rule([rule, overlapping, default], _ticket())
    with pytest.raises(RoutingConfigurationError):
        service._select_rule([rule], _ticket())


def test_support_managers_cannot_assign_outside_their_groups() -> None:
    service = object.__new__(RoutingService)
    service._authorization = AuthorizationService()
    own_group = UUID("23000000-0000-0000-0000-000000000001")
    other_group = UUID("23000000-0000-0000-0000-000000000002")
    manager = RequestContext(
        tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
        user_id=UUID("22000000-0000-0000-0000-000000000003"),
        external_subject="support-manager",
        roles=frozenset({"SUPPORT_MANAGER"}),
        support_group_ids=frozenset({own_group}),
        business_unit_id=None,
        correlation_id="00000000-0000-0000-0000-000000000001",
        request_id="routing-group-scope",
    )
    service._authorize_group(manager, own_group)
    with pytest.raises(AuthorizationError):
        service._authorize_group(manager, other_group)

    administrator = replace(manager, roles=frozenset({"PROJECT_ADMIN"}))
    service._authorize_group(administrator, other_group)
