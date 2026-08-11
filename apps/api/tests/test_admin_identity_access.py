"""Contract tests for read-only users/roles/queues administration (Task 11.5B)."""

from typing import Any, cast

from fastapi.testclient import TestClient

from apps.api.app.identity.authorization import ROLE_PERMISSIONS, Permission

USERS_PATH = "/api/v1/admin/users"
USER_DETAIL_PATH = "/api/v1/admin/users/{user_id}"
ROLES_PATH = "/api/v1/admin/roles"
ROLE_DETAIL_PATH = "/api/v1/admin/roles/{role_code}"
QUEUES_PATH = "/api/v1/admin/queues"
QUEUE_DETAIL_PATH = "/api/v1/admin/queues/{support_group_id}"
TICKET_VIEWS_PATH = "/api/v1/admin/ticket-views"

ALL_PATHS = (
    USERS_PATH,
    USER_DETAIL_PATH,
    ROLES_PATH,
    ROLE_DETAIL_PATH,
    QUEUES_PATH,
    QUEUE_DETAIL_PATH,
    TICKET_VIEWS_PATH,
)

NEW_SCHEMAS = (
    "AdminUserSummary",
    "AdminUserListResponse",
    "AdminUserRoleItem",
    "AdminUserMembershipItem",
    "AdminExternalIdentityItem",
    "AdminUserDetailResponse",
    "AdminRoleSummary",
    "AdminRoleListResponse",
    "AdminPermissionGroup",
    "AdminRoleAssignmentItem",
    "AdminRoleDetailResponse",
    "AdminQueueSummary",
    "AdminQueueListResponse",
    "AdminQueueMemberItem",
    "AdminQueueDetailResponse",
    "AdminTicketViewSummary",
    "AdminTicketViewListResponse",
)


def _contract(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", client.get("/openapi.json").json())


def _schemas(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["components"]["schemas"])


def _operation(client: TestClient, path: str) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["paths"][path]["get"])


def _response_ref(operation: dict[str, Any]) -> str:
    return cast(
        "str", operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    )


def _parameter_names(operation: dict[str, Any]) -> set[str]:
    return {parameter["name"] for parameter in operation.get("parameters", [])}


def test_identity_admin_endpoints_require_authentication(client: TestClient) -> None:
    requests = (
        USERS_PATH,
        USERS_PATH + "/6e0d8a1c-52a5-4b3f-9b34-8a4f0a4a2b10",
        ROLES_PATH,
        ROLES_PATH + "/AGENT",
        QUEUES_PATH,
        QUEUES_PATH + "/6e0d8a1c-52a5-4b3f-9b34-8a4f0a4a2b10",
        TICKET_VIEWS_PATH,
    )
    for path in requests:
        assert client.get(path).status_code == 401, path


def test_users_list_contract(client: TestClient) -> None:
    operation = _operation(client, USERS_PATH)
    assert _response_ref(operation).endswith("AdminUserListResponse")
    assert {
        "search",
        "active",
        "role_code",
        "support_group_id",
        "provider_code",
        "limit",
        "offset",
    } <= _parameter_names(operation)
    properties = _schemas(client)["AdminUserSummary"]["properties"]
    for field in (
        "user_id",
        "display_name",
        "email_address",
        "active_flag",
        "business_unit_name",
        "role_codes",
        "support_group_names",
        "identity_provider_codes",
        "created_at",
        "updated_at",
    ):
        assert field in properties, field
    list_properties = _schemas(client)["AdminUserListResponse"]["properties"]
    assert {"items", "has_more"} <= set(list_properties)


def test_user_detail_contract(client: TestClient) -> None:
    operation = _operation(client, USER_DETAIL_PATH)
    assert _response_ref(operation).endswith("AdminUserDetailResponse")
    properties = _schemas(client)["AdminUserDetailResponse"]["properties"]
    for field in (
        "user_id",
        "display_name",
        "email_address",
        "active_flag",
        "business_unit_name",
        "locale_code",
        "timezone_name",
        "provisioning",
        "oidc_linked",
        "roles",
        "effective_permission_codes",
        "memberships",
        "external_identities",
        "recent_security_events",
        "created_at",
        "updated_at",
    ):
        assert field in properties, field
    role_properties = _schemas(client)["AdminUserRoleItem"]["properties"]
    assert {"role_code", "role_name", "active_flag", "valid_from", "valid_to"} <= set(
        role_properties
    )
    membership_properties = _schemas(client)["AdminUserMembershipItem"]["properties"]
    assert {"support_group_id", "group_name", "member_role", "active_flag", "joined_at"} <= set(
        membership_properties
    )
    identity_properties = _schemas(client)["AdminExternalIdentityItem"]["properties"]
    assert set(identity_properties) == {"provider_code", "active_flag", "last_authenticated_at"}


def test_roles_contracts(client: TestClient) -> None:
    list_operation = _operation(client, ROLES_PATH)
    assert _response_ref(list_operation).endswith("AdminRoleListResponse")
    assert {"search", "limit", "offset"} <= _parameter_names(list_operation)
    summary_properties = _schemas(client)["AdminRoleSummary"]["properties"]
    for field in (
        "role_code",
        "role_name",
        "description",
        "system_role_flag",
        "active_flag",
        "permission_count",
        "assigned_user_count",
    ):
        assert field in summary_properties, field
    detail_operation = _operation(client, ROLE_DETAIL_PATH)
    assert _response_ref(detail_operation).endswith("AdminRoleDetailResponse")
    assert {"limit", "offset"} <= _parameter_names(detail_operation)
    detail_properties = _schemas(client)["AdminRoleDetailResponse"]["properties"]
    for field in (
        "role_code",
        "role_name",
        "description",
        "system_role_flag",
        "active_flag",
        "permission_groups",
        "assignments",
        "assignments_has_more",
    ):
        assert field in detail_properties, field
    group_properties = _schemas(client)["AdminPermissionGroup"]["properties"]
    assert set(group_properties) == {"domain", "permission_codes"}
    assignment_properties = _schemas(client)["AdminRoleAssignmentItem"]["properties"]
    assert {
        "user_id",
        "display_name",
        "email_address",
        "active_flag",
        "valid_from",
        "valid_to",
    } <= set(assignment_properties)


def test_queue_contracts(client: TestClient) -> None:
    list_operation = _operation(client, QUEUES_PATH)
    assert _response_ref(list_operation).endswith("AdminQueueListResponse")
    assert {"search", "active", "limit", "offset"} <= _parameter_names(list_operation)
    summary_properties = _schemas(client)["AdminQueueSummary"]["properties"]
    for field in (
        "support_group_id",
        "group_code",
        "group_name",
        "contact_email",
        "assignment_method",
        "active_flag",
        "member_count",
        "created_at",
        "updated_at",
    ):
        assert field in summary_properties, field
    detail_operation = _operation(client, QUEUE_DETAIL_PATH)
    assert _response_ref(detail_operation).endswith("AdminQueueDetailResponse")
    detail_properties = _schemas(client)["AdminQueueDetailResponse"]["properties"]
    for field in (
        "support_group_id",
        "group_code",
        "group_name",
        "contact_email",
        "assignment_method",
        "active_flag",
        "manager_display_name",
        "members",
        "ticket_views",
        "created_at",
        "updated_at",
    ):
        assert field in detail_properties, field
    member_properties = _schemas(client)["AdminQueueMemberItem"]["properties"]
    assert set(member_properties) == {
        "user_id",
        "display_name",
        "member_role",
        "active_flag",
        "joined_at",
    }


def test_ticket_views_contract(client: TestClient) -> None:
    operation = _operation(client, TICKET_VIEWS_PATH)
    assert _response_ref(operation).endswith("AdminTicketViewListResponse")
    assert {"limit", "offset"} <= _parameter_names(operation)
    properties = _schemas(client)["AdminTicketViewSummary"]["properties"]
    for field in (
        "queue_id",
        "queue_name",
        "description",
        "project_code",
        "visibility",
        "display_order",
        "version_status",
        "active_flag",
    ):
        assert field in properties, field


def test_identity_admin_schemas_expose_no_sensitive_fields(client: TestClient) -> None:
    schemas = _schemas(client)
    forbidden_fragments = (
        "subject",
        "issuer",
        "password",
        "hash",
        "token",
        "secret",
        "credential",
        "dsn",
    )
    forbidden_names = (
        "employee_number",
        "capacity_points",
        "granted_by",
        "filter_json",
        "sort_json",
        "columns_json",
        "organization_claim_value",
        "safe_provider_metadata_json",
        "client_ip",
        "user_agent",
    )
    for schema_name in NEW_SCHEMAS:
        properties = schemas[schema_name]["properties"]
        for name in properties:
            lowered = name.lower()
            for fragment in forbidden_fragments:
                assert fragment not in lowered, f"{schema_name}.{name}"
        for name in forbidden_names:
            assert name not in properties, f"{schema_name}.{name}"


def test_identity_admin_permission_grants_are_unchanged() -> None:
    assert Permission.ADMIN_IDENTITY_READ in ROLE_PERMISSIONS["PLATFORM_ADMIN"]
    for role_code in (
        "AGENT",
        "SUPPORT_MANAGER",
        "CUSTOMER",
        "PROJECT_ADMIN",
        "AUDITOR",
        "KNOWLEDGE_AUTHOR",
        "SERVICE_OWNER",
    ):
        assert Permission.ADMIN_IDENTITY_READ not in ROLE_PERMISSIONS[role_code], role_code
