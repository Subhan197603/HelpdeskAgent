"""Contract tests for access-administration mutations (Task 11.5F)."""

from typing import Any, cast

from fastapi.testclient import TestClient

from apps.api.app.identity.authorization import ROLE_PERMISSIONS, Permission

STATUS_PATH = "/api/v1/admin/users/{user_id}/status"
ASSIGN_PATH = "/api/v1/admin/users/{user_id}/roles"
REMOVE_PATH = "/api/v1/admin/users/{user_id}/roles/{role_code}"
MEMBER_ADD_PATH = "/api/v1/admin/queues/{support_group_id}/members"
MEMBER_REMOVE_PATH = "/api/v1/admin/queues/{support_group_id}/members/{user_id}"

MUTATION_OPERATIONS = (
    (STATUS_PATH, "patch"),
    (ASSIGN_PATH, "post"),
    (REMOVE_PATH, "delete"),
    (MEMBER_ADD_PATH, "post"),
    (MEMBER_REMOVE_PATH, "delete"),
)

NEW_SCHEMAS = (
    "AdminUserStatusRequest",
    "AdminUserStatusResponse",
    "AdminRoleAssignRequest",
    "AdminRoleAssignmentChangeResponse",
    "AdminQueueMemberRequest",
    "AdminQueueMemberChangeResponse",
)


def _contract(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", client.get("/openapi.json").json())


def _schemas(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["components"]["schemas"])


def _operation(client: TestClient, path: str, method: str) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["paths"][path][method])


def test_mutation_endpoints_require_authentication(client: TestClient) -> None:
    user = "6e0d8a1c-52a5-4b3f-9b34-8a4f0a4a2b10"
    group = "7f1e9b2d-63b6-4c40-8c45-9b5f1b5b3c21"
    requests = (
        client.patch(
            STATUS_PATH.format(user_id=user),
            json={"active": False, "expected_updated_at": "2030-01-01T00:00:00Z"},
        ),
        client.post(ASSIGN_PATH.format(user_id=user), json={"role_code": "AGENT"}),
        client.delete(REMOVE_PATH.format(user_id=user, role_code="AGENT")),
        client.post(MEMBER_ADD_PATH.format(support_group_id=group), json={"user_id": user}),
        client.delete(MEMBER_REMOVE_PATH.format(support_group_id=group, user_id=user)),
    )
    for response in requests:
        assert response.status_code == 401


def test_mutation_contracts_document_error_statuses(client: TestClient) -> None:
    for path, method in MUTATION_OPERATIONS:
        operation = _operation(client, path, method)
        responses = set(operation["responses"])
        assert {"401", "403", "404", "422"} <= responses, f"{method} {path}"
    for path, method in ((STATUS_PATH, "patch"), (REMOVE_PATH, "delete")):
        operation = _operation(client, path, method)
        assert "409" in operation["responses"], f"{method} {path}"


def test_mutation_request_and_response_schemas(client: TestClient) -> None:
    schemas = _schemas(client)
    for name in NEW_SCHEMAS:
        assert name in schemas, name
    assert set(schemas["AdminUserStatusRequest"]["properties"]) == {
        "active",
        "expected_updated_at",
    }
    assert set(schemas["AdminUserStatusResponse"]["properties"]) == {
        "user_id",
        "active_flag",
        "updated_at",
        "changed",
    }
    assign = schemas["AdminRoleAssignRequest"]["properties"]
    assert set(assign) == {"role_code"}
    assert assign["role_code"]["pattern"] == "^[A-Z][A-Z0-9_]{0,59}$"
    assert set(schemas["AdminRoleAssignmentChangeResponse"]["properties"]) == {
        "user_id",
        "role_code",
        "valid_from",
        "changed",
    }
    member_request = schemas["AdminQueueMemberRequest"]["properties"]
    assert set(member_request) == {"user_id", "member_role"}
    assert set(schemas["AdminQueueMemberChangeResponse"]["properties"]) == {
        "support_group_id",
        "user_id",
        "member_role",
        "changed",
    }


def test_mutation_schemas_expose_no_sensitive_fields(client: TestClient) -> None:
    schemas = _schemas(client)
    forbidden_fragments = ("subject", "issuer", "password", "hash", "token", "secret", "credential")
    for schema_name in NEW_SCHEMAS:
        for name in schemas[schema_name]["properties"]:
            lowered = name.lower()
            for fragment in forbidden_fragments:
                assert fragment not in lowered, f"{schema_name}.{name}"
        assert "granted_by" not in schemas[schema_name]["properties"], schema_name


def test_admin_identity_write_grants() -> None:
    assert Permission.ADMIN_IDENTITY_WRITE in ROLE_PERMISSIONS["PLATFORM_ADMIN"]
    for role_code in ROLE_PERMISSIONS:
        if role_code == "PLATFORM_ADMIN":
            continue
        assert Permission.ADMIN_IDENTITY_WRITE not in ROLE_PERMISSIONS[role_code], role_code


def test_write_permission_never_granted_by_read() -> None:
    read_only_roles = [
        role
        for role, permissions in ROLE_PERMISSIONS.items()
        if Permission.ADMIN_IDENTITY_READ in permissions
        and Permission.ADMIN_IDENTITY_WRITE not in permissions
    ]
    assert read_only_roles == [], (
        "No role should hold ADMIN_IDENTITY_READ without WRITE today; "
        f"unexpected read-only administrator roles: {read_only_roles}"
    )
