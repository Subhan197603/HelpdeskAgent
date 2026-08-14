"""Contract tests for the analyst ticket-detail extensions (Task 11.3)."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.app.tickets.schemas import AgentTicketResponse

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
        "watched",
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


def test_agent_detail_classification_fields_are_required_and_nullable(
    client: TestClient,
) -> None:
    schema = _schemas(client)["AgentTicketResponse"]
    assert {"impact_code", "urgency_code"} <= set(schema["required"])
    for field in ("impact_code", "urgency_code"):
        assert schema["properties"][field]["anyOf"] == [
            {"type": "string"},
            {"type": "null"},
        ]


@pytest.mark.parametrize(
    ("impact", "urgency"),
    [
        ("MODERATE", "HIGH"),
        (None, "HIGH"),
        ("MODERATE", None),
        (None, None),
    ],
)
def test_agent_detail_serializes_schema_valid_classification_values(
    impact: str | None, urgency: str | None
) -> None:
    response = AgentTicketResponse(
        id=UUID("86000000-0000-0000-0000-000000000001"),
        key="ERP-1",
        summary="Classification compatibility",
        description=None,
        project_code="ERP",
        project_name="ERP support",
        request_type_code="FUSION_ERROR",
        request_type_name="Report an Oracle Fusion error",
        service_name="Oracle Fusion ERP",
        environment_name=None,
        work_type="INCIDENT",
        status="OPEN",
        status_name="Open",
        priority="P2",
        reporter_user_id=UUID("22000000-0000-0000-0000-000000000004"),
        reporter_name="Analyst",
        requested_for_user_id=None,
        requested_for_name=None,
        created_at=datetime(2030, 6, 15, tzinfo=UTC),
        updated_at=datetime(2030, 6, 15, tzinfo=UTC),
        creation_event_at=None,
        row_version=1,
        impact_code=impact,
        urgency_code=urgency,
        assignment_group_id=None,
        assignment_group_name=None,
        assignee_user_id=None,
        assignee_name=None,
        watched=False,
    )

    payload = response.model_dump(mode="json")
    assert payload["impact_code"] == impact
    assert payload["urgency_code"] == urgency


def test_customer_ticket_contract_gains_no_analyst_fields(client: TestClient) -> None:
    properties = _schemas(client)["TicketResponse"]["properties"]
    for field in ("slas", "impact_code", "urgency_code", "assignee_name", "watched"):
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
