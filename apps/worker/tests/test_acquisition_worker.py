"""Knowledge acquisition validation and network-boundary tests."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from apps.api.app.ingestion.models import ManifestEntry
from apps.api.app.knowledge.models import KnowledgeSource
from apps.worker.worker.acquisition_worker import (
    AcquisitionWork,
    HttpDocumentFetcher,
    PermanentAcquisitionError,
    RedirectedPageError,
    RemovedPageError,
    _detect_mime,
    _permission_reasons,
    _require_public_host,
    _validate_content,
)
from apps.worker.worker.settings import WorkerSettings

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = UUID("20000000-0000-0000-0000-000000000001")


def _work(**manifest_overrides: object) -> AcquisitionWork:
    source = KnowledgeSource(
        UUID("25000000-0000-0000-0000-000000000001"),
        TENANT,
        "POLICIES",
        "Policies",
        "COMPANY_POLICY",
        None,
        "manual:policies",
        "MANUAL_UPLOAD",
        False,
        "change-1",
        "EMPLOYEE",
        "ACTIVE",
        "APPROVED",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "en-GB",
        None,
        NOW,
        2,
        NOW,
        NOW,
        "CURRENT",
        None,
        None,
        None,
        None,
        None,
        None,
    )
    manifest_values: dict[str, object] = {
        "manifest_entry_id": UUID("26000000-0000-0000-0000-000000000001"),
        "tenant_id": TENANT,
        "source_id": source.source_id,
        "manifest_key": "policy-1",
        "document_title": "Policy",
        "document_type": "POLICY",
        "audience_code": "EMPLOYEE",
        "canonical_url": None,
        "pdf_url": None,
        "html_url": None,
        "target_collection": "policy",
        "security_classification": "INTERNAL",
        "acquisition_permission": "NOT_REQUIRED",
        "permission_reference": None,
        "acquisition_method": "MANUAL_UPLOAD",
        "enabled_flag": True,
        "expected_sha256": None,
        "original_filename": "policy.txt",
        "declared_content_type": "text/plain",
        "declared_size_bytes": 6,
        "source_last_modified_at": None,
        "copyright_notice": None,
        "approved_by": None,
        "approved_at": None,
        "row_version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    manifest_values.update(manifest_overrides)
    manifest = ManifestEntry(**manifest_values)  # type: ignore[arg-type]
    return AcquisitionWork(
        UUID("27000000-0000-0000-0000-000000000001"),
        UUID("28000000-0000-0000-0000-000000000001"),
        TENANT,
        1,
        2,
        1,
        "quarantine/tenant/item/policy.txt",
        manifest,
        source,
        None,
    )


@pytest.mark.parametrize(
    ("content", "filename", "expected"),
    [
        (b"%PDF-1.7", "guide.pdf", "application/pdf"),
        (b'{"safe":true}', "data.json", "application/json"),
        (b"heading\n", "readme.md", "text/markdown"),
        (b"a,b\n1,2\n", "data.csv", "text/csv"),
    ],
)
def test_content_detection(content: bytes, filename: str, expected: str) -> None:
    assert _detect_mime(content, filename) == expected


@pytest.mark.parametrize(
    ("overrides", "content", "provider", "error"),
    [
        ({}, b"", "text/plain", "EMPTY_DOCUMENT"),
        ({"declared_size_bytes": 7}, b"policy", "text/plain", "DECLARED_SIZE_MISMATCH"),
        ({}, b"policy", "text/html", "PROVIDER_CONTENT_TYPE_MISMATCH"),
        (
            {"original_filename": "policy.pdf", "declared_content_type": "application/pdf"},
            b"policy",
            "application/pdf",
            "DETECTED_CONTENT_TYPE_MISMATCH",
        ),
    ],
)
def test_content_validation_fails_closed(
    overrides: dict[str, object], content: bytes, provider: str, error: str
) -> None:
    with pytest.raises(PermanentAcquisitionError, match=error):
        _validate_content(_work(**overrides), content, provider, WorkerSettings())


def test_source_and_manifest_versions_are_immutable_job_snapshots() -> None:
    work = _work(row_version=3)
    assert _permission_reasons(work, WorkerSettings()) == ["MANIFEST_VERSION_CHANGED"]


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "::1"])
def test_fetch_boundary_rejects_non_public_addresses(host: str) -> None:
    with pytest.raises(PermanentAcquisitionError, match="NON_PUBLIC"):
        asyncio.run(_require_public_host(host, 443))


def _mock_fetcher(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    original_client = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        return original_client(timeout=kwargs.get("timeout"), transport=transport)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", client)


def test_fetcher_classifies_removed_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_fetcher(monkeypatch, httpx.Response(410))
    with pytest.raises(RemovedPageError) as info:
        asyncio.run(HttpDocumentFetcher(1.0).fetch("https://93.184.216.34/gone.pdf", 1024))
    assert info.value.status_code == 410
    assert str(info.value) == "REMOTE_PAGE_REMOVED"


def test_fetcher_records_redirects_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_fetcher(
        monkeypatch,
        httpx.Response(301, headers={"location": "https://docs.example.invalid/new.pdf"}),
    )
    with pytest.raises(RedirectedPageError) as info:
        asyncio.run(HttpDocumentFetcher(1.0).fetch("https://93.184.216.34/moved.pdf", 1024))
    assert info.value.status_code == 301
    assert info.value.target == "https://docs.example.invalid/new.pdf"
    assert str(info.value) == "REMOTE_PAGE_REDIRECTED"


def test_page_signals_stay_final_for_ordinary_acquisition_runs() -> None:
    assert issubclass(RemovedPageError, PermanentAcquisitionError)
    assert issubclass(RedirectedPageError, PermanentAcquisitionError)
    work = _work()
    assert work.run_type == "ACQUISITION"
    assert work.previous_sha256 is None
