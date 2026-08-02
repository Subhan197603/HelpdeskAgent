"""Approval rule resolution and outcome tests."""

from typing import cast
from uuid import UUID

import pytest

from apps.api.app.approvals.models import ApprovalDefinition, ApprovalTicket
from apps.api.app.approvals.repository import ApprovalRepository
from apps.api.app.approvals.service import (
    ApprovalConfigurationError,
    ApprovalEngine,
    _terminal_status,
)

TENANT = UUID("20000000-0000-0000-0000-000000000001")
PROJECT = UUID("30000000-0000-0000-0000-000000000006")
TICKET = UUID("40000000-0000-0000-0000-000000000001")
REQUESTER = UUID("22000000-0000-0000-0000-000000000005")
APPROVER = UUID("22000000-0000-0000-0000-000000000006")


class FakeApprovalRepository:
    def __init__(self, definition: ApprovalDefinition) -> None:
        self.definition = definition
        self.ticket_record = ApprovalTicket(TICKET, TENANT, "SEC-1", PROJECT, REQUESTER, None)
        self.created_approvers: list[UUID] | None = None

    async def ticket(self, tenant_id: UUID, ticket_id: UUID) -> ApprovalTicket | None:
        assert (tenant_id, ticket_id) == (TENANT, TICKET)
        return self.ticket_record

    async def published_definition(
        self, tenant_id: UUID, project_id: UUID, approval_code: str
    ) -> ApprovalDefinition | None:
        assert (tenant_id, project_id, approval_code) == (TENANT, PROJECT, "ACCESS")
        return self.definition

    async def active_users(self, tenant_id: UUID, user_ids: list[UUID]) -> set[UUID]:
        assert tenant_id == TENANT
        return set(user_ids)

    async def manager_for(self, tenant_id: UUID, user_id: UUID) -> UUID | None:
        assert (tenant_id, user_id) == (TENANT, REQUESTER)
        return APPROVER

    async def create(self, *args: object) -> UUID:
        self.created_approvers = cast("list[UUID]", args[2])
        return UUID("41000000-0000-0000-0000-000000000001")


def _definition(mode: str, rule: object, *, self_approval: bool = False) -> ApprovalDefinition:
    return ApprovalDefinition(
        UUID("38600000-0000-0000-0000-000000000001"),
        UUID("38700000-0000-0000-0000-000000000001"),
        TENANT,
        PROJECT,
        "ACCESS",
        "Access approval",
        mode,
        rule,
        UUID("32300000-0000-0000-0000-000000000008"),
        UUID("32300000-0000-0000-0000-000000000009"),
        self_approval,
        None,
    )


@pytest.mark.anyio
async def test_manager_resolution_uses_requested_users_active_manager() -> None:
    repository = FakeApprovalRepository(
        _definition("MANAGER_APPROVAL", {"subject": "REQUESTED_FOR_OR_REPORTER"})
    )
    engine = ApprovalEngine(cast("ApprovalRepository", repository))
    await engine.request(TENANT, TICKET, "ACCESS", APPROVER, str(TENANT), "request")
    assert repository.created_approvers == [APPROVER]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["ANY_ONE_APPROVER", "ALL_APPROVERS"])
async def test_parallel_modes_resolve_unique_active_users(mode: str) -> None:
    repository = FakeApprovalRepository(
        _definition(mode, {"user_ids": [str(APPROVER), str(APPROVER)]})
    )
    engine = ApprovalEngine(cast("ApprovalRepository", repository))
    await engine.request(TENANT, TICKET, "ACCESS", APPROVER, str(TENANT), "request")
    assert repository.created_approvers == [APPROVER]


@pytest.mark.anyio
async def test_requester_self_approval_fails_closed_unless_version_opts_in() -> None:
    repository = FakeApprovalRepository(
        _definition("ANY_ONE_APPROVER", {"user_ids": [str(REQUESTER)]})
    )
    engine = ApprovalEngine(cast("ApprovalRepository", repository))
    with pytest.raises(ApprovalConfigurationError, match="requester"):
        await engine.request(TENANT, TICKET, "ACCESS", APPROVER, str(TENANT), "request")

    repository.definition = _definition(
        "ANY_ONE_APPROVER", {"user_ids": [str(REQUESTER)]}, self_approval=True
    )
    await engine.request(TENANT, TICKET, "ACCESS", APPROVER, str(TENANT), "request")
    assert repository.created_approvers == [REQUESTER]


def test_supported_modes_reach_deterministic_terminal_states() -> None:
    assert _terminal_status("ANY_ONE_APPROVER", 3, 1, 0) == "APPROVED"
    assert _terminal_status("ANY_ONE_APPROVER", 3, 0, 2) is None
    assert _terminal_status("ANY_ONE_APPROVER", 3, 0, 3) == "REJECTED"
    assert _terminal_status("ALL_APPROVERS", 3, 2, 0) is None
    assert _terminal_status("ALL_APPROVERS", 3, 3, 0) == "APPROVED"
    assert _terminal_status("ALL_APPROVERS", 3, 1, 1) == "REJECTED"
    assert _terminal_status("MANAGER_APPROVAL", 1, 1, 0) == "APPROVED"
    assert _terminal_status("MANAGER_APPROVAL", 1, 0, 1) == "REJECTED"
    with pytest.raises(ApprovalConfigurationError, match="not supported"):
        _terminal_status("SEQUENTIAL_APPROVAL", 2, 1, 0)
