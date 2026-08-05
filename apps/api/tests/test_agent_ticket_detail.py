"""Contract tests for the analyst ticket-detail extensions (Task 11.3)."""

from typing import Any, cast

from fastapi.testclient import TestClient

DETAIL_PATH = "/api/v1/agent/tickets/{ticket_key}"
ATTACHMENTS_PATH = "/api/v1/agent/tickets/{ticket_key}/attachments"


def _schemas(client: TestClient) -> dict[str, Any]:
    contract = cast("dict[str, Any]", client.get("/openapi.json").json())
    return cast("dict[str, Any]", contract["components"]["schemas"])


def test_agent_detail_exposes_assignment_impact_and_sla_fields(client: TestClient) -> None:
    contract = client.get("/openapi.json").json()
    operation = contract["paths"][DETAIL_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("AgentTicketResponse")
    properties = _schemas(client)["AgentTicketResponse"]["properties"]
    for field in (
        "impact_code",
        "urgency_code",
        "assignment_group_id",
        "assignment_group_name",
        "assignee_user_id",
        "assignee_name",
        "slas",
    ):
        assert field in properties, field
    sla_properties = _schemas(client)["AgentTicketSlaSummary"]["properties"]
    for field in (
        "definition_code",
        "state_code",
        "target_at",
        "remaining_working_seconds",
        "paused_at",
        "breached_at",
        "completed_at",
    ):
        assert field in properties["slas"] and False or field in sla_properties, field


def test_customer_ticket_contract_gains_no_analyst_fields(client: TestClient) -> None:
    properties = _schemas(client)["TicketResponse"]["properties"]
    for field in ("slas", "impact_code", "urgency_code", "assignee_name"):
        assert field not in properties, field


def test_attachment_list_endpoint_exists_and_requires_authentication(
    client: TestClient,
) -> None:
    contract = client.get("/openapi.json").json()
    operation = contract["paths"][ATTACHMENTS_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("AttachmentListResponse")
    assert client.get("/api/v1/agent/tickets/ERP-1/attachments").status_code == 401


def test_attachment_list_contract_is_metadata_only(client: TestClient) -> None:
    properties = _schemas(client)["AttachmentSummaryResponse"]["properties"]
    for field in (
        "id",
        "filename",
        "content_type",
        "size_bytes",
        "scan_status",
        "visibility",
        "uploaded_by_name",
        "created_at",
    ):
        assert field in properties, field
    for forbidden in ("url", "download_url", "object_key", "quarantine_object_uri"):
        assert forbidden not in properties, forbidden
