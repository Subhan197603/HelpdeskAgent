"""Contract tests for the administration shell (Task 11.5A)."""

from typing import Any, cast

from fastapi.testclient import TestClient

from apps.api.app.identity.authorization import ROLE_PERMISSIONS, Permission

OVERVIEW_PATH = "/api/v1/admin/overview"
SYSTEM_STATUS_PATH = "/api/v1/admin/system-status"
AUDIT_EVENTS_PATH = "/api/v1/admin/audit/events"
SECURITY_EVENTS_PATH = "/api/v1/admin/audit/security-events"


def _contract(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", client.get("/openapi.json").json())


def _schemas(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["components"]["schemas"])


def test_admin_endpoints_require_authentication(client: TestClient) -> None:
    for path in (OVERVIEW_PATH, SYSTEM_STATUS_PATH, AUDIT_EVENTS_PATH, SECURITY_EVENTS_PATH):
        assert client.get(path).status_code == 401, path


def test_overview_contract_exposes_real_counts_only(client: TestClient) -> None:
    operation = _contract(client)["paths"][OVERVIEW_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("AdminOverviewResponse")
    properties = _schemas(client)["AdminOverviewResponse"]["properties"]
    for field in (
        "active_users",
        "support_groups",
        "open_tickets",
        "published_knowledge_documents",
    ):
        assert field in properties, field


def test_system_status_contract_exposes_no_secrets(client: TestClient) -> None:
    operation = _contract(client)["paths"][SYSTEM_STATUS_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("SystemStatusResponse")
    properties = _schemas(client)["SystemStatusResponse"]["properties"]
    for field in (
        "app_version",
        "environment",
        "migration_head",
        "oidc_enabled",
        "developer_identity_enabled",
        "ai_globally_enabled",
        "object_storage_enabled",
        "clamav_required",
        "metrics_endpoint_enabled",
        "rls_enabled",
        "retrieval_embedding_provider",
        "dependencies",
    ):
        assert field in properties, field
    forbidden_fragments = ("url", "key", "secret", "password", "token", "dsn", "credential")
    for name in properties:
        lowered = name.lower()
        for fragment in forbidden_fragments:
            assert fragment not in lowered, name
    dependency_properties = _schemas(client)["DependencyStatusItem"]["properties"]
    for field in ("name", "status", "required"):
        assert field in dependency_properties, field


def test_audit_event_contract_withholds_raw_payloads(client: TestClient) -> None:
    operation = _contract(client)["paths"][AUDIT_EVENTS_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("AuditEventListResponse")
    parameters = {parameter["name"] for parameter in operation.get("parameters", [])}
    assert {
        "resource_type",
        "action_code",
        "outcome_code",
        "occurred_from",
        "occurred_to",
        "limit",
        "offset",
    } <= parameters
    properties = _schemas(client)["AuditEventSummary"]["properties"]
    for field in (
        "id",
        "actor_id",
        "actor_type",
        "action_code",
        "resource_type",
        "resource_id",
        "outcome_code",
        "failure_reason",
        "change_summary",
        "correlation_id",
        "request_id",
        "occurred_at",
    ):
        assert field in properties, field
    for forbidden in ("previous_values_json", "new_values_json", "source_ip", "user_agent"):
        assert forbidden not in properties, forbidden


def test_security_event_contract_withholds_client_fingerprints(client: TestClient) -> None:
    operation = _contract(client)["paths"][SECURITY_EVENTS_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("SecurityEventListResponse")
    parameters = {parameter["name"] for parameter in operation.get("parameters", [])}
    assert {"event_type", "decision_code", "limit", "offset"} <= parameters
    properties = _schemas(client)["SecurityEventSummary"]["properties"]
    for field in (
        "id",
        "event_type",
        "decision_code",
        "user_id",
        "resource_type",
        "resource_id",
        "details",
        "occurred_at",
    ):
        assert field in properties, field
    for forbidden in ("client_ip", "user_agent"):
        assert forbidden not in properties, forbidden


def test_application_migration_head_resolves_from_revision_files() -> None:
    from apps.api.app.admin.service import application_migration_head

    head = application_migration_head()
    assert head is not None
    assert head == "0024_analyst_saved_filters"


def test_admin_permissions_are_granted_to_expected_roles_only() -> None:
    assert Permission.AUDIT_EVENT_READ in ROLE_PERMISSIONS["PLATFORM_ADMIN"]
    assert Permission.AUDIT_EVENT_READ in ROLE_PERMISSIONS["AUDITOR"]
    assert Permission.SYSTEM_HEALTH_READ in ROLE_PERMISSIONS["PLATFORM_ADMIN"]
    for role_code in ("AGENT", "SUPPORT_MANAGER", "CUSTOMER", "PROJECT_ADMIN"):
        assert Permission.AUDIT_EVENT_READ not in ROLE_PERMISSIONS[role_code], role_code
        assert Permission.SYSTEM_HEALTH_READ not in ROLE_PERMISSIONS[role_code], role_code
        assert Permission.ADMIN_IDENTITY_READ not in ROLE_PERMISSIONS[role_code], role_code
