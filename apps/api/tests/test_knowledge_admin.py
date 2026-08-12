"""Contracts for tenant-scoped Knowledge Administration (Task 11.5D)."""

from typing import Any, cast

from fastapi.testclient import TestClient

LIST_PATH = "/api/v1/admin/knowledge/documents"
DETAIL_PATH = "/api/v1/admin/knowledge/documents/{document_id}"
PREVIEW_PATH = "/api/v1/admin/knowledge/documents/{document_id}/versions/{version_id}/preview"


def _contract(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", client.get("/openapi.json").json())


def _schemas(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["components"]["schemas"])


def test_admin_list_contract_is_bounded_and_filterable(client: TestClient) -> None:
    operation = _contract(client)["paths"][LIST_PATH]["get"]
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("DocumentAdminListResponse")
    parameters = {parameter["name"] for parameter in operation["parameters"]}
    assert {
        "search",
        "approval_status",
        "publication_state",
        "audience_code",
        "security_classification",
        "document_type",
        "source_id",
        "owner_group_id",
        "limit",
        "offset",
    } <= parameters


def test_admin_detail_and_preview_expose_safe_governance_views(client: TestClient) -> None:
    contract = _contract(client)
    assert contract["paths"][DETAIL_PATH]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("DocumentAdminResponse")
    preview = contract["paths"][PREVIEW_PATH]["get"]
    assert preview["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "DocumentPreviewResponse"
    )
    detail = _schemas(client)["DocumentAdminResponse"]["properties"]
    for field in (
        "source_name",
        "owner_group_name",
        "publication_state",
        "current_version_number",
        "permission_summary",
        "publication_events",
    ):
        assert field in detail
    permission = _schemas(client)["DocumentPermissionSummaryResponse"]["properties"]
    assert "principal_code" not in permission
    assert "evidence_json" not in detail


def test_admin_reads_require_the_dedicated_permission(client: TestClient) -> None:
    document_id = "00000000-0000-0000-0000-000000000001"
    version_id = "00000000-0000-0000-0000-000000000002"
    assert client.get(LIST_PATH).status_code == 401
    assert client.get(DETAIL_PATH.format(document_id=document_id)).status_code == 401
    assert (
        client.get(
            PREVIEW_PATH.format(document_id=document_id, version_id=version_id),
            params={"processing_version_id": "00000000-0000-0000-0000-000000000003"},
        ).status_code
        == 401
    )
