"""Knowledge-source contracts and fail-closed URL validation."""

from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.schemas import SourceCreate
from apps.api.app.knowledge.service import _canonical

OWNER = UUID("22000000-0000-0000-0000-000000000007")
TENANT = UUID("20000000-0000-0000-0000-000000000001")


def _source(**overrides: object) -> SourceCreate:
    values: dict[str, object] = {
        "code": "POLICY_SOURCE",
        "name": "Policy source",
        "source_type": "COMPANY_POLICY",
        "canonical_location": "repository:knowledge/policy",
        "acquisition_method": "MANUAL_UPLOAD",
        "audience_scope": "EMPLOYEE",
        "owner_user_id": OWNER,
    }
    values.update(overrides)
    return SourceCreate.model_validate(values)


@pytest.mark.parametrize("audience", ["EMPLOYEE", "ANALYST", "RESTRICTED", "ADMINISTRATIVE"])
def test_all_governed_audiences_are_explicit(audience: str) -> None:
    assert _source(audience_scope=audience).audience_scope == audience


@pytest.mark.parametrize("status", ["ACTIVE", "DISABLED", "RETIRED"])
def test_all_source_lifecycle_states_are_explicit(status: str) -> None:
    assert _source(status=status).status == status


def test_source_requires_an_owner_and_distinct_product_module() -> None:
    with pytest.raises(PydanticValidationError, match="source owner"):
        _source(owner_user_id=None)
    node = UUID("24000000-0000-0000-0000-000000000001")
    with pytest.raises(PydanticValidationError, match="must be different"):
        _source(product_node_id=node, module_node_id=node)


@pytest.mark.parametrize(
    "location",
    [
        "http://example.invalid/file",
        "https://user:secret@example.invalid/file",
        "https://example.invalid/file?token=secret",
        "https://example.invalid/file#fragment",
    ],
)
def test_external_canonical_locations_fail_closed(location: str) -> None:
    source = _source(
        source_type="OTHER_EXTERNAL",
        acquisition_method="APPROVED_DIRECT_DOWNLOAD",
        canonical_location=location,
    )
    with pytest.raises(ValidationError):
        _canonical(source)


def test_external_canonical_location_is_normalized_without_query_material() -> None:
    source = _source(
        source_type="OTHER_EXTERNAL",
        acquisition_method="APPROVED_DIRECT_DOWNLOAD",
        canonical_location="HTTPS://DOCS.EXAMPLE.INVALID/policy",
    )
    assert _canonical(source) == "https://docs.example.invalid/policy"


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (
            "KNOWLEDGE_AUTHOR",
            Permission.KNOWLEDGE_SOURCE_UPDATE,
            Permission.KNOWLEDGE_SOURCE_APPROVE,
        ),
        (
            "KNOWLEDGE_APPROVER",
            Permission.KNOWLEDGE_SOURCE_APPROVE,
            Permission.KNOWLEDGE_SOURCE_UPDATE,
        ),
        (
            "CUSTOMER",
            Permission.CATALOG_SERVICE_READ,
            Permission.KNOWLEDGE_SOURCE_READ_ADMIN,
        ),
    ],
)
def test_source_administration_roles_are_separated(
    role: str, allowed: Permission, denied: Permission
) -> None:
    context = RequestContext(
        tenant_id=TENANT,
        user_id=OWNER,
        external_subject="knowledge-role-test",
        roles=frozenset({role}),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id=str(TENANT),
        request_id="knowledge-role-test",
    )
    authorization = AuthorizationService()
    assert authorization.is_allowed(context, allowed)
    assert not authorization.is_allowed(context, denied)
