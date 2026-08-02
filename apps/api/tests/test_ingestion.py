"""Acquisition contract, authorization, and fail-closed validation tests."""

from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import UnsupportedFileError, ValidationError
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.ingestion.schemas import ManifestEntryInput, ManifestImportCommand
from apps.api.app.ingestion.service import _require_content, _safe_https_url

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000007")
SOURCE = UUID("25000000-0000-0000-0000-000000000001")


def _manifest(**overrides: object) -> ManifestEntryInput:
    values: dict[str, object] = {
        "source_id": SOURCE,
        "manifest_key": "policy-001",
        "document_title": "Approved policy",
        "document_type": "POLICY",
        "audience_code": "EMPLOYEE",
        "acquisition_url": "https://docs.example.invalid/policy.pdf",
        "target_collection": "company-policy",
        "acquisition_method": "APPROVED_DIRECT_DOWNLOAD",
        "original_filename": "policy.pdf",
        "declared_content_type": "application/pdf",
    }
    values.update(overrides)
    return ManifestEntryInput.model_validate(values)


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.invalid/policy.pdf",
        "https://user:secret@docs.example.invalid/policy.pdf",
        "https://docs.example.invalid/policy.pdf?token=secret",
        "https://docs.example.invalid/policy.pdf#section",
        "https://localhost/policy.pdf",
        "https://127.0.0.1/policy.pdf",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/policy.pdf",
    ],
)
def test_acquisition_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValidationError):
        _safe_https_url(url)


def test_acquisition_url_is_normalized_without_query_material() -> None:
    assert (
        _safe_https_url(" HTTPS://DOCS.EXAMPLE.INVALID/policy.pdf ")
        == "https://docs.example.invalid/policy.pdf"
    )


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("policy.exe", "application/octet-stream"), ("policy.pdf", "text/html")],
)
def test_document_extension_and_content_type_must_match(filename: str, content_type: str) -> None:
    with pytest.raises(UnsupportedFileError):
        _require_content(filename, content_type, 10)


def test_manifest_batch_rejects_duplicate_source_keys() -> None:
    with pytest.raises(ValueError, match="unique"):
        ManifestImportCommand(entries=[_manifest(), _manifest()])


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (
            "KNOWLEDGE_AUTHOR",
            Permission.KNOWLEDGE_MANIFEST_IMPORT,
            Permission.KNOWLEDGE_MANIFEST_APPROVE,
        ),
        (
            "KNOWLEDGE_APPROVER",
            Permission.KNOWLEDGE_MANIFEST_APPROVE,
            Permission.KNOWLEDGE_MANIFEST_IMPORT,
        ),
        (
            "CUSTOMER",
            Permission.CATALOG_SERVICE_READ,
            Permission.KNOWLEDGE_DOCUMENT_UPLOAD,
        ),
    ],
)
def test_acquisition_administration_roles_are_separated(
    role: str, allowed: Permission, denied: Permission
) -> None:
    context = RequestContext(
        tenant_id=TENANT,
        user_id=USER,
        external_subject="acquisition-role-test",
        roles=frozenset({role}),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id=str(TENANT),
        request_id="acquisition-role-test",
    )
    authorization = AuthorizationService()
    assert authorization.is_allowed(context, allowed)
    assert not authorization.is_allowed(context, denied)
