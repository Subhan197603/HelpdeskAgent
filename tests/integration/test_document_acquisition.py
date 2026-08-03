"""PostgreSQL integration coverage for governed document acquisition."""

import asyncio
import hashlib
import json
import logging
import math
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.attachments.clamav import MalwareScanner, ScanResult
from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app
from apps.api.app.retrieval.models import (
    RetrievalCandidates,
    RetrievalEvidenceSet,
    RetrievalFilters,
    RetrievalRequest,
)
from apps.api.app.retrieval.service import RetrievalService
from apps.worker.worker.acquisition_worker import (
    AcquisitionWorker,
    FetchedDocument,
    RetryableAcquisitionError,
)
from apps.worker.worker.knowledge_processing_worker import KnowledgeProcessingWorker
from apps.worker.worker.settings import WorkerSettings
from ingestion.chunkers import ChunkingConfig, SemanticChunker
from ingestion.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingError,
    EmbeddingProvider,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-acquisition-test"
PORT = "55463"
DATABASE = "acquisition_test"
TENANT_ID = "20000000-0000-0000-0000-000000000001"
AUTHOR_ID = "22000000-0000-0000-0000-000000000007"


class HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def create_upload_url(
        self, key: str, content_type: str, size: int, checksum: str, expires: int
    ) -> str:
        del size, checksum, expires
        return f"https://uploads.example.invalid/{key}?signature=redacted&type={content_type}"

    async def read(self, key: str, maximum_bytes: int) -> bytes:
        content = self.objects[key][0]
        if len(content) > maximum_bytes:
            raise RuntimeError("test object exceeded maximum")
        return content

    async def write(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)

    async def copy(self, source: str, destination: str, content_type: str) -> None:
        self.objects[destination] = (self.objects[source][0], content_type)

    async def promote(self, source: str, destination: str, content_type: str) -> None:
        await self.copy(source, destination, content_type)
        await self.reject(source)

    async def reject(self, key: str) -> None:
        self.objects.pop(key, None)

    async def create_download_url(self, key: str, filename: str, expires: int) -> str:
        del filename, expires
        return f"https://downloads.example.invalid/{key}"


class CleanScanner:
    async def scan(self, content: bytes) -> ScanResult:
        assert content
        return ScanResult(True, "TestScanner", "1.0")


class InfectedScanner:
    async def scan(self, content: bytes) -> ScanResult:
        assert content
        return ScanResult(False, "TestScanner", "1.0", "Integration.Test.Signature")


class SequenceFetcher:
    def __init__(self, content: bytes, *, fail_once: bool = False) -> None:
        self.content = content
        self.fail_once = fail_once
        self.calls = 0

    async def fetch(self, url: str, maximum_bytes: int) -> FetchedDocument:
        assert url.startswith("https://docs.example.invalid/")
        assert len(self.content) <= maximum_bytes
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RetryableAcquisitionError("REMOTE_FETCH_UNAVAILABLE")
        return FetchedDocument(self.content, "application/pdf")


class FailOnceEmbeddingProvider:
    model_code = "DEFAULT_1536"
    dimension = 1536

    def __init__(self) -> None:
        self.calls: list[int] = []
        self._failed = False
        self._delegate = DeterministicEmbeddingProvider(self.model_code, self.dimension)

    async def embed_batch(self, inputs: list[str]) -> list[list[float]]:
        self.calls.append(len(inputs))
        if not self._failed:
            self._failed = True
            raise EmbeddingError("TRANSIENT_TEST_FAILURE")
        return await self._delegate.embed_batch(inputs)


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and result.returncode:
        pytest.fail(result.stdout + result.stderr)
    return result


def _psql(sql: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        DATABASE,
        "-Atqc",
        sql,
        check=check,
    )


def _value(sql: str) -> str:
    return _psql(sql).stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def acquisition_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            arguments = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                arguments += ["-v", "app_password=helpdesk"]
            _compose(*arguments, "-U", "postgres", "-d", DATABASE, "-f", file)
        migration_environment = os.environ.copy()
        migration_environment["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
        )
        for command in ("stamp", "upgrade"):
            result = subprocess.run(
                ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", command],
                cwd=ROOT,
                env=migration_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        for file in ("/development/identity_personas.sql", "/baseline/09_optional_rls.sql"):
            _compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                DATABASE,
                "-f",
                file,
            )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


@pytest.fixture(scope="module")
def application() -> Iterator[tuple[TestClient, FastAPI, MemoryStorage]]:
    settings = Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}",
            "developer_identity_enabled": True,
            "object_storage_enabled": True,
            "rls_enabled": True,
            "trusted_hosts": ["testserver"],
        }
    )
    resources = ApplicationResources(
        Database(settings), HealthyProbe(), HealthyProbe(), HealthyProbe()
    )
    app = create_app(settings, resource_factory=lambda _: resources)
    storage = MemoryStorage()
    app.state.ingestion_service._storage = storage
    with TestClient(
        app,
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        yield client, app, storage


def _headers(persona: str, key: str | None = None) -> dict[str, str]:
    headers = {"X-Developer-User": f"DEV/{persona}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _create_approved_source(client: TestClient, code: str, method: str) -> dict[str, Any]:
    external = method != "MANUAL_UPLOAD"
    body = {
        "code": code,
        "name": f"Acquisition source {code}",
        "source_type": "OTHER_EXTERNAL" if external else "COMPANY_POLICY",
        "canonical_location": (
            "https://docs.example.invalid/library" if external else f"repository:{code.lower()}"
        ),
        "acquisition_method": method,
        "permission_reference": "source-governance-1",
        "audience_scope": "EMPLOYEE",
        "status": "ACTIVE",
        "owner_user_id": AUTHOR_ID,
        "scope": "TENANT",
    }
    created = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", f"create-{code.lower()}"),
        json=body,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    approved = client.post(
        f"/api/v1/admin/knowledge/sources/{source['id']}/approval-decisions",
        headers=_headers("platform-admin", f"approve-{code.lower()}"),
        json={"decision": "APPROVED", "expected_version": 1},
    )
    assert approved.status_code == 200, approved.text
    if external:
        authorized = client.post(
            f"/api/v1/admin/knowledge/sources/{source['id']}/acquisition-authorizations",
            headers=_headers("platform-admin", f"authorize-{code.lower()}"),
            json={
                "decision": "APPROVED",
                "acquisition_method": method,
                "permission_reference": "licensed-download-1",
                "expected_version": 2,
            },
        )
        assert authorized.status_code == 201, authorized.text
        source = authorized.json()["source"]
    else:
        source = approved.json()
    return cast("dict[str, Any]", source)


def _import_manifest(
    client: TestClient, source_id: str, key: str, expected_sha256: str | None = None
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/admin/knowledge/manifest/import",
        headers=_headers("knowledge-author", f"import-{key}"),
        json={
            "entries": [
                {
                    "source_id": source_id,
                    "manifest_key": key,
                    "document_title": "Acquired PDF",
                    "document_type": "POLICY",
                    "audience_code": "EMPLOYEE",
                    "acquisition_url": f"https://docs.example.invalid/{key}.pdf",
                    "target_collection": "policies",
                    "security_classification": "INTERNAL",
                    "acquisition_method": "APPROVED_DIRECT_DOWNLOAD",
                    "original_filename": f"{key}.pdf",
                    "declared_content_type": "application/pdf",
                    "expected_sha256": expected_sha256,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json()["items"][0])


def _approve_manifest(client: TestClient, entry: dict[str, Any], key: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/admin/knowledge/manifest/{entry['id']}/approval-decisions",
        headers=_headers("platform-admin", f"approve-manifest-{key}"),
        json={
            "decision": "APPROVED",
            "permission_reference": "manifest-review-1",
            "expected_version": entry["row_version"],
        },
    )
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


def _create_run(client: TestClient, entry_id: str, key: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/admin/ingestion/runs",
        headers=_headers("knowledge-author", f"run-{key}"),
        json={"manifest_entry_ids": [entry_id]},
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json())


async def _process(
    storage: MemoryStorage,
    fetcher: SequenceFetcher,
    *,
    concurrent: bool = False,
    scanner: MalwareScanner | None = None,
) -> tuple[bool, bool | None]:
    settings = WorkerSettings.model_validate(
        {
            "app_env": "integration",
            "worker_database_url": (
                f"postgresql+psycopg://helpdesk_worker_login:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
            ),
            "worker_id": f"acquisition-{uuid4()}",
        }
    )
    engine = create_async_engine(settings.worker_database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    selected_scanner = scanner or CleanScanner()
    first = AcquisitionWorker(sessions, settings, storage, selected_scanner, fetcher)
    try:
        if not concurrent:
            return await first.process_one(), None
        second_settings = settings.model_copy(update={"worker_id": f"acquisition-{uuid4()}"})
        second = AcquisitionWorker(sessions, second_settings, storage, selected_scanner, fetcher)
        one, two = await asyncio.gather(first.process_one(), second.process_one())
        return one, two
    finally:
        await engine.dispose()


async def _process_knowledge(storage: MemoryStorage, chunker: SemanticChunker | None = None) -> int:
    settings = WorkerSettings.model_validate(
        {
            "app_env": "integration",
            "worker_database_url": (
                f"postgresql+psycopg://helpdesk_worker_login:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
            ),
            "worker_id": f"processing-{uuid4()}",
            "embedding_provider_mode": "deterministic",
        }
    )
    engine = create_async_engine(settings.worker_database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    worker = KnowledgeProcessingWorker(sessions, settings, storage, chunker=chunker)
    processed = 0
    try:
        while await worker.process_one():
            processed += 1
        return processed
    finally:
        await engine.dispose()


async def _process_knowledge_once(
    storage: MemoryStorage,
    embeddings: EmbeddingProvider,
    chunker: SemanticChunker,
    *,
    concurrent: bool = False,
) -> tuple[bool, bool | None]:
    settings = WorkerSettings.model_validate(
        {
            "app_env": "integration",
            "worker_database_url": (
                f"postgresql+psycopg://helpdesk_worker_login:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
            ),
            "worker_id": f"processing-{uuid4()}",
            "embedding_provider_mode": "deterministic",
            "embedding_batch_size": 1,
        }
    )
    engine = create_async_engine(settings.worker_database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first = KnowledgeProcessingWorker(
        sessions, settings, storage, embeddings=embeddings, chunker=chunker
    )
    try:
        if not concurrent:
            return await first.process_one(), None
        second = KnowledgeProcessingWorker(
            sessions,
            settings.model_copy(update={"worker_id": f"processing-{uuid4()}"}),
            storage,
            embeddings=embeddings,
            chunker=chunker,
        )
        one, two = await asyncio.gather(first.process_one(), second.process_one())
        return one, two
    finally:
        await engine.dispose()


async def _retrieve(context: RequestContext, request: RetrievalRequest) -> RetrievalCandidates:
    settings = Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": (f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"),
            "rls_enabled": True,
        }
    )
    engine = create_async_engine(settings.database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = RetrievalService(
        lambda identity: SqlAlchemyUnitOfWork(sessions, identity, rls_enabled=True),
        AuthorizationService(),
        settings,
    )
    try:
        return await service.search(context, request)
    finally:
        await engine.dispose()


async def _retrieve_evidence(
    context: RequestContext,
    query: str,
    filters: RetrievalFilters,
    *,
    persona: str = "EMPLOYEE",
) -> RetrievalEvidenceSet:
    settings = Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": (f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"),
            "rls_enabled": True,
        }
    )
    engine = create_async_engine(settings.database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = RetrievalService(
        lambda identity: SqlAlchemyUnitOfWork(sessions, identity, rls_enabled=True),
        AuthorizationService(),
        settings,
    )
    try:
        return await service.evidence(
            context, query=query, filters=filters, limit=8, persona=persona
        )
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_permission_gate_retry_concurrency_acquisition_and_duplicate_skip(
    application: tuple[TestClient, FastAPI, MemoryStorage],
) -> None:
    client, _, storage = application
    source = _create_approved_source(client, "ACQUIRE_PDF", "APPROVED_DIRECT_DOWNLOAD")
    pending = _import_manifest(client, source["id"], "approved-guide")

    denied = client.post(
        "/api/v1/admin/ingestion/runs",
        headers=_headers("knowledge-author", "unapproved-run"),
        json={"manifest_entry_ids": [pending["id"]]},
    )
    assert denied.status_code == 403

    approved = _approve_manifest(client, pending, "approved-guide")
    run = _create_run(client, approved["id"], "approved-guide")
    content = b"%PDF-1.7\napproved content\n"
    fetcher = SequenceFetcher(content, fail_once=True)
    first, _ = asyncio.run(_process(storage, fetcher), loop_factory=asyncio.SelectorEventLoop)
    assert first is True
    assert (
        _value(
            f"SELECT item_status FROM kb.ingestion_run_item WHERE ingestion_run_id='{run['id']}'"
        )
        == "FAILED"
    )
    _psql(
        "UPDATE kb.ingestion_run_item SET next_attempt_at=now() "
        f"WHERE ingestion_run_id='{run['id']}'"
    )
    concurrent = asyncio.run(
        _process(storage, fetcher, concurrent=True), loop_factory=asyncio.SelectorEventLoop
    )
    assert concurrent in {(True, False), (False, True)}
    item = client.get(
        f"/api/v1/admin/ingestion/runs/{run['id']}", headers=_headers("knowledge-author")
    ).json()["items"][0]
    assert item["status"] == "ACQUIRED"
    assert item["attempt_count"] == 2
    assert item["sha256_checksum"]
    object_key = _value(
        "SELECT original_file_uri FROM kb.document_version WHERE document_version_id="
        f"'{item['document_version_id']}'"
    )
    assert object_key.startswith(f"knowledge/{TENANT_ID}/ACQUIRE_PDF/")
    assert object_key.endswith("/original/approved-guide.pdf")
    assert storage.objects[object_key][0] == content

    reimported = _import_manifest(client, source["id"], "approved-guide")
    reapproved = _approve_manifest(client, reimported, "approved-guide-duplicate")
    duplicate_run = _create_run(client, reapproved["id"], "approved-guide-duplicate")
    processed, _ = asyncio.run(
        _process(storage, SequenceFetcher(content)), loop_factory=asyncio.SelectorEventLoop
    )
    assert processed is True
    duplicate_status = _value(
        "SELECT item_status FROM kb.ingestion_run_item "
        f"WHERE ingestion_run_id='{duplicate_run['id']}'"
    )
    assert duplicate_status == "SKIPPED_UNCHANGED"
    assert _value("SELECT count(*) FROM kb.document_version") == "1"
    assert _value("SELECT count(*) FROM kb.ingestion_event") == "3"
    assert set(
        _value("SELECT event_code FROM kb.ingestion_event ORDER BY event_code").splitlines()
    ) == {
        "ACQUISITION_FAILED",
        "ACQUISITION_SKIPPED_UNCHANGED",
        "DOCUMENT_ACQUIRED",
    }


@pytest.mark.integration
def test_manual_upload_is_quarantined_and_database_stores_only_metadata(
    application: tuple[TestClient, FastAPI, MemoryStorage],
) -> None:
    client, _, storage = application
    source = _create_approved_source(client, "MANUAL_POLICY", "MANUAL_UPLOAD")
    content = b"manual policy\n"
    checksum = hashlib.sha256(content).hexdigest()
    authorized = client.post(
        "/api/v1/admin/knowledge/manual-uploads",
        headers=_headers("knowledge-author", "manual-policy-upload"),
        json={
            "source_id": source["id"],
            "manifest_key": "manual-policy-1",
            "document_title": "Manual policy",
            "document_type": "POLICY",
            "audience_code": "EMPLOYEE",
            "target_collection": "policies",
            "filename": "manual-policy.txt",
            "content_type": "text/plain",
            "file_size_bytes": len(content),
            "sha256_checksum": checksum,
        },
    )
    assert authorized.status_code == 201, authorized.text
    upload = authorized.json()
    assert upload["quarantine_object_key"].startswith("quarantine/knowledge/")
    storage.objects[upload["quarantine_object_key"]] = (content, "text/plain")
    complete = client.post(
        f"/api/v1/admin/knowledge/manual-uploads/{upload['item_id']}/complete",
        headers=_headers("knowledge-author", "manual-policy-complete"),
    )
    assert complete.status_code == 200, complete.text
    processed, _ = asyncio.run(
        _process(storage, SequenceFetcher(b"unused")), loop_factory=asyncio.SelectorEventLoop
    )
    assert processed is True
    assert (
        _value(f"SELECT count(*) FROM kb.document_version WHERE sha256_checksum='{checksum}'")
        == "1"
    )
    assert (
        _value(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='kb' "
            "AND table_name IN "
            "('ingestion_manifest_entry','ingestion_run_item','document_version') "
            "AND column_name IN ('file_bytes','content_bytes','provider_credential','access_token')"
        )
        == "0"
    )
    immutable = _psql("UPDATE kb.ingestion_event SET outcome_code='ALTERED'", check=False)
    assert immutable.returncode != 0


@pytest.mark.integration
def test_checksum_and_malware_failures_are_final_and_leave_no_document_version(
    application: tuple[TestClient, FastAPI, MemoryStorage],
) -> None:
    client, _, storage = application
    source = _create_approved_source(client, "REJECTED_PDF", "APPROVED_DIRECT_DOWNLOAD")

    checksum_entry = _import_manifest(client, source["id"], "checksum-failure", "0" * 64)
    checksum_entry = _approve_manifest(client, checksum_entry, "checksum-failure")
    checksum_run = _create_run(client, checksum_entry["id"], "checksum-failure")
    processed, _ = asyncio.run(
        _process(storage, SequenceFetcher(b"%PDF-1.7\nwrong checksum\n")),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert processed is True
    assert (
        _value(
            "SELECT item_status || ':' || error_code FROM kb.ingestion_run_item "
            f"WHERE ingestion_run_id='{checksum_run['id']}'"
        )
        == "FAILED:CHECKSUM_MISMATCH"
    )

    malware_entry = _import_manifest(client, source["id"], "malware-failure")
    malware_entry = _approve_manifest(client, malware_entry, "malware-failure")
    malware_run = _create_run(client, malware_entry["id"], "malware-failure")
    processed, _ = asyncio.run(
        _process(
            storage,
            SequenceFetcher(b"%PDF-1.7\nmalware fixture\n"),
            scanner=InfectedScanner(),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert processed is True
    assert (
        _value(
            "SELECT item_status || ':' || error_code || ':' || malware_scan_status "
            "FROM kb.ingestion_run_item "
            f"WHERE ingestion_run_id='{malware_run['id']}'"
        )
        == "FAILED:MALWARE_DETECTED:INFECTED"
    )
    assert (
        _value(
            "SELECT count(*) FROM kb.document_version version "
            "JOIN kb.document document USING (document_id) "
            f"WHERE document.source_id='{source['id']}'"
        )
        == "0"
    )


@pytest.mark.integration
def test_versioned_processing_publication_reprocessing_and_retirement(
    application: tuple[TestClient, FastAPI, MemoryStorage],
) -> None:
    client, _, storage = application
    source = _create_approved_source(client, "PUBLISH_POLICY", "MANUAL_UPLOAD")
    content = (
        b"# Access policy\n\nEmployees must use approved access.\n\n"
        b"## Procedure\n\n1. Request access.\n2. Obtain approval.\n3. Verify access.\n"
    )
    checksum = hashlib.sha256(content).hexdigest()
    authorized = client.post(
        "/api/v1/admin/knowledge/manual-uploads",
        headers=_headers("knowledge-author", "publish-policy-upload"),
        json={
            "source_id": source["id"],
            "manifest_key": "publish-policy-1",
            "document_title": "Access policy",
            "document_type": "POLICY",
            "audience_code": "EMPLOYEE",
            "target_collection": "policies",
            "filename": "access-policy.md",
            "content_type": "text/markdown",
            "file_size_bytes": len(content),
            "sha256_checksum": checksum,
            "copyright_notice": "Copyright Example Corporation",
        },
    )
    assert authorized.status_code == 201, authorized.text
    upload = authorized.json()
    storage.objects[upload["quarantine_object_key"]] = (content, "text/markdown")
    assert (
        client.post(
            f"/api/v1/admin/knowledge/manual-uploads/{upload['item_id']}/complete",
            headers=_headers("knowledge-author", "publish-policy-complete"),
        ).status_code
        == 200
    )
    acquired, _ = asyncio.run(
        _process(storage, SequenceFetcher(b"unused")), loop_factory=asyncio.SelectorEventLoop
    )
    assert acquired is True
    assert asyncio.run(_process_knowledge(storage), loop_factory=asyncio.SelectorEventLoop) >= 1
    document_id = _value(
        "SELECT document_id FROM kb.document WHERE external_document_key='publish-policy-1'"
    )
    document = client.get(
        f"/api/v1/admin/knowledge/documents/{document_id}",
        headers=_headers("knowledge-author"),
    )
    assert document.status_code == 200, document.text
    body = document.json()
    processing = body["versions"][0]["processing_versions"][0]
    assert processing["status"] == "COMPLETED"
    assert processing["validation_status"] == "WARNING"
    assert processing["chunk_count"] == processing["embedded_chunk_count"]
    assert processing["chunk_count"] > 0
    assert (
        client.get(
            f"/api/v1/admin/knowledge/documents/{document_id}",
            headers=_headers("customer"),
        ).status_code
        == 403
    )
    premature = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/publication",
        headers=_headers("platform-admin", "premature-publication"),
        json={
            "processing_version_id": processing["id"],
            "expected_document_version": body["row_version"],
            "reason": "Attempt before document approval",
        },
    )
    assert premature.status_code == 409
    assert (
        _value(f"SELECT count(*) FROM kb.v_active_document_chunk WHERE document_id='{document_id}'")
        == "0"
    )

    approved = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/approval-decisions",
        headers=_headers("platform-admin", "approve-publish-policy"),
        json={
            "decision": "APPROVED",
            "expected_version": body["row_version"],
            "reason": "Human knowledge review completed",
        },
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    published = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/publication",
        headers=_headers("platform-admin", "publish-policy-version-1"),
        json={
            "processing_version_id": processing["id"],
            "expected_document_version": approved_body["row_version"],
            "reason": "Validated company policy publication",
        },
    )
    assert published.status_code == 200, published.text
    published_body = published.json()
    assert published_body["versions"][0]["current"] is True
    first_visible = _value(
        f"SELECT count(*) FROM kb.v_active_document_chunk WHERE document_id='{document_id}'"
    )
    assert int(first_visible) == processing["chunk_count"]

    _psql(
        "UPDATE kb.ingestion_run_item SET pipeline_stage='PROCESSING',item_status='ACQUIRED',"
        "final_failure=false,processing_next_attempt_at=now() "
        f"WHERE document_id='{document_id}'"
    )
    changed_chunker = SemanticChunker(ChunkingConfig(100, 160, 50, 10))
    flaky_embeddings = FailOnceEmbeddingProvider()
    concurrent = asyncio.run(
        _process_knowledge_once(storage, flaky_embeddings, changed_chunker, concurrent=True),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert concurrent in {(True, False), (False, True)}
    assert (
        _value(f"SELECT item_status FROM kb.ingestion_run_item WHERE document_id='{document_id}'")
        == "FAILED"
    )
    _psql(
        "UPDATE kb.ingestion_run_item SET processing_next_attempt_at=now() "
        f"WHERE document_id='{document_id}'"
    )
    retried = asyncio.run(
        _process_knowledge_once(storage, flaky_embeddings, changed_chunker),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert retried == (True, None)
    assert len(flaky_embeddings.calls) >= 2
    assert all(batch_size == 1 for batch_size in flaky_embeddings.calls)
    refreshed = client.get(
        f"/api/v1/admin/knowledge/documents/{document_id}",
        headers=_headers("knowledge-author"),
    ).json()
    processing_versions = refreshed["versions"][0]["processing_versions"]
    assert len(processing_versions) == 2
    assert len({item["chunking_configuration_hash"] for item in processing_versions}) == 2
    assert (
        _value(f"SELECT count(*) FROM kb.v_active_document_chunk WHERE document_id='{document_id}'")
        == first_visible
    )

    republished = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/publication",
        headers=_headers("platform-admin", "publish-policy-version-2"),
        json={
            "processing_version_id": processing_versions[0]["id"],
            "expected_document_version": refreshed["row_version"],
            "reason": "Publish reviewed chunking revision",
        },
    )
    assert republished.status_code == 200, republished.text
    republished_body = republished.json()
    assert (
        _value(
            "SELECT count(*) FROM kb.document_publication_event "
            f"WHERE document_id='{document_id}' AND action_code='PUBLISHED'"
        )
        == "2"
    )
    evidence = _value(
        "SELECT evidence_json->>'embedding_model_code' "
        "FROM kb.document_publication_event "
        f"WHERE document_id='{document_id}' ORDER BY occurred_at DESC LIMIT 1"
    )
    assert evidence == "DEFAULT_1536"

    retired = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/retirement",
        headers=_headers("platform-admin", "retire-publish-policy"),
        json={
            "expected_version": republished_body["row_version"],
            "reason": "Policy superseded by governance decision",
        },
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["approval_status"] == "RETIRED"
    assert (
        _value(f"SELECT count(*) FROM kb.v_active_document_chunk WHERE document_id='{document_id}'")
        == "0"
    )
    immutable = _psql(
        "UPDATE kb.document_publication_event SET action_code='RETIRED' "
        f"WHERE document_id='{document_id}'",
        check=False,
    )
    assert immutable.returncode != 0


@pytest.mark.integration
def test_failed_parsing_cannot_be_published(
    application: tuple[TestClient, FastAPI, MemoryStorage],
) -> None:
    client, _, storage = application
    source = _create_approved_source(client, "FAILED_PARSE", "MANUAL_UPLOAD")
    content = b"%PDF-1.7\nthis is not a valid PDF document"
    checksum = hashlib.sha256(content).hexdigest()
    authorized = client.post(
        "/api/v1/admin/knowledge/manual-uploads",
        headers=_headers("knowledge-author", "failed-parse-upload"),
        json={
            "source_id": source["id"],
            "manifest_key": "failed-parse-1",
            "document_title": "Invalid text document",
            "document_type": "PROCEDURE",
            "audience_code": "EMPLOYEE",
            "target_collection": "procedures",
            "filename": "invalid.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": len(content),
            "sha256_checksum": checksum,
            "copyright_notice": "Copyright Example Corporation",
        },
    )
    assert authorized.status_code == 201, authorized.text
    upload = authorized.json()
    storage.objects[upload["quarantine_object_key"]] = (content, "application/pdf")
    completed = client.post(
        f"/api/v1/admin/knowledge/manual-uploads/{upload['item_id']}/complete",
        headers=_headers("knowledge-author", "failed-parse-complete"),
    )
    assert completed.status_code == 200, completed.text
    assert asyncio.run(
        _process(storage, SequenceFetcher(b"unused")),
        loop_factory=asyncio.SelectorEventLoop,
    )[0]
    assert (
        _value(
            "SELECT item_status || ':' || pipeline_stage FROM kb.ingestion_run_item "
            "WHERE manifest_entry_id=(SELECT manifest_entry_id FROM kb.ingestion_manifest_entry "
            "WHERE manifest_key='failed-parse-1')"
        )
        == "ACQUIRED:PROCESSING"
    )
    assert asyncio.run(_process_knowledge(storage), loop_factory=asyncio.SelectorEventLoop) == 1

    document_id = _value(
        "SELECT document_id FROM kb.document WHERE external_document_key='failed-parse-1'"
    )
    document = client.get(
        f"/api/v1/admin/knowledge/documents/{document_id}",
        headers=_headers("knowledge-author"),
    )
    assert document.status_code == 200, document.text
    body = document.json()
    version = body["versions"][0]
    processing = version["processing_versions"][0]
    assert version["extraction_status"] == "FAILED"
    assert processing["status"] == "FAILED"
    assert processing["validation_status"] == "FAILED"

    approved = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/approval-decisions",
        headers=_headers("platform-admin", "approve-failed-parse"),
        json={
            "decision": "APPROVED",
            "expected_version": body["row_version"],
            "reason": "Exercise the publication safety gate",
        },
    )
    assert approved.status_code == 200, approved.text
    publication = client.post(
        f"/api/v1/admin/knowledge/documents/{document_id}/publication",
        headers=_headers("platform-admin", "publish-failed-parse"),
        json={
            "processing_version_id": processing["id"],
            "expected_document_version": approved.json()["row_version"],
            "reason": "This must be rejected",
        },
    )
    assert publication.status_code == 409, publication.text
    assert (
        _value(f"SELECT count(*) FROM kb.v_active_document_chunk WHERE document_id='{document_id}'")
        == "0"
    )


def _seed_retrieval_corpus() -> tuple[str, dict[str, str]]:
    vector = "[1," + ",".join("0" for _ in range(1535)) + "]"
    ids = {
        "apps": "34000000-0000-0000-0000-000000000001",
        "fdi": "34000000-0000-0000-0000-000000000002",
        "analyst": "34000000-0000-0000-0000-000000000003",
        "denied": "34000000-0000-0000-0000-000000000004",
        "other_tenant": "34000000-0000-0000-0000-000000000005",
    }
    _psql(
        "INSERT INTO kb.release(release_family,release_code,release_name) VALUES "
        "('FUSION_APPLICATIONS','26C','Fusion 26C'),"
        "('FUSION_DATA_INTELLIGENCE','26.R2','FDI 26.R2') "
        "ON CONFLICT (release_family,release_code) DO NOTHING"
    )
    apps_release = _value(
        "SELECT release_id FROM kb.release "
        "WHERE release_family='FUSION_APPLICATIONS' AND release_code='26C'"
    )
    fdi_release = _value(
        "SELECT release_id FROM kb.release "
        "WHERE release_family='FUSION_DATA_INTELLIGENCE' AND release_code='26.R2'"
    )
    _psql(
        f"""
        INSERT INTO kb.product_node(product_node_id,tenant_id,parent_product_node_id,
          product_code,product_name,product_level,release_family)
        VALUES
          ('33000000-0000-0000-0000-000000000001','{TENANT_ID}',NULL,
            'FINANCIALS','Financials','PRODUCT','FUSION_APPLICATIONS'),
          ('33000000-0000-0000-0000-000000000002','{TENANT_ID}',
            '33000000-0000-0000-0000-000000000001','ACCOUNTS_PAYABLE',
            'Accounts Payable','MODULE','FUSION_APPLICATIONS'),
          ('33000000-0000-0000-0000-000000000003','{TENANT_ID}',NULL,
            'FDI','Fusion Data Intelligence','PRODUCT','FUSION_DATA_INTELLIGENCE'),
          ('33000000-0000-0000-0000-000000000004','{TENANT_ID}',
            '33000000-0000-0000-0000-000000000003','FDI_FINANCIALS',
            'FDI Financials','MODULE','FUSION_DATA_INTELLIGENCE');
        INSERT INTO kb.source(source_id,tenant_id,source_code,source_name,source_type,
          acquisition_method,canonical_location,active_flag,approval_status,owner_user_id,
          approved_by,approved_at)
        VALUES
          ('31000000-0000-0000-0000-000000000001','{TENANT_ID}','RETRIEVAL_COMPANY',
            'Company policy source','COMPANY_POLICY','MANUAL_UPLOAD',
            'https://knowledge.example.invalid/company',true,'APPROVED','{AUTHOR_ID}',
            '22000000-0000-0000-0000-000000000001',now()),
          ('31000000-0000-0000-0000-000000000002','{TENANT_ID}','RETRIEVAL_ORACLE',
            'Oracle documentation source','ORACLE_PUBLIC_DOCUMENTATION','MANUAL_UPLOAD',
            'https://docs.example.invalid/oracle',true,'APPROVED','{AUTHOR_ID}',
            '22000000-0000-0000-0000-000000000001',now()),
          ('31000000-0000-0000-0000-000000000003','{TENANT_ID}','RETRIEVAL_ANALYST',
            'Analyst source','INTERNAL_KNOWLEDGE','MANUAL_UPLOAD',
            'https://knowledge.example.invalid/analyst',true,'APPROVED','{AUTHOR_ID}',
            '22000000-0000-0000-0000-000000000001',now()),
          ('31000000-0000-0000-0000-000000000004','{TENANT_ID}','RETRIEVAL_DENIED',
            'Restricted role source','INTERNAL_KNOWLEDGE','MANUAL_UPLOAD',
            'https://knowledge.example.invalid/restricted',true,'APPROVED','{AUTHOR_ID}',
            '22000000-0000-0000-0000-000000000001',now());
        INSERT INTO kb.document(document_id,tenant_id,source_id,product_node_id,release_id,
          external_document_key,document_title,document_type,audience_code,language_code,
          security_classification,approval_status,active_flag)
        VALUES
          ('{ids["apps"]}','{TENANT_ID}','31000000-0000-0000-0000-000000000001',
            '33000000-0000-0000-0000-000000000002',
            '{apps_release}','retrieval-apps-26c',
            'Resolve Invoice Validation Holds','POLICY','EMPLOYEE','en','INTERNAL','APPROVED',true),
          ('{ids["fdi"]}','{TENANT_ID}','31000000-0000-0000-0000-000000000002',
            '33000000-0000-0000-0000-000000000004',
            '{fdi_release}','retrieval-fdi-26r2','FDI Invoice Validation Analytics',
            'USER_GUIDE','EMPLOYEE','en','PUBLIC','APPROVED',true),
          ('{ids["analyst"]}','{TENANT_ID}','31000000-0000-0000-0000-000000000003',
            '33000000-0000-0000-0000-000000000002',
            '{apps_release}','retrieval-analyst',
            'Analyst Invoice Diagnostic','RUNBOOK','ANALYST','en','CONFIDENTIAL','APPROVED',true),
          ('{ids["denied"]}','{TENANT_ID}','31000000-0000-0000-0000-000000000004',
            '33000000-0000-0000-0000-000000000002',
            '{apps_release}','retrieval-denied',
            'Privileged Invoice Secret','RUNBOOK','EMPLOYEE','en','INTERNAL','APPROVED',true);
        INSERT INTO kb.document_permission(
          document_id,principal_type,principal_code,permission_code)
        VALUES
          ('{ids["analyst"]}','ALL_ANALYSTS','ANALYST','READ'),
          ('{ids["denied"]}','ROLE','KNOWLEDGE_APPROVER','READ'),
          ('{ids["denied"]}','SUPPORT_GROUP','FUSION_AP','READ'),
          ('{ids["denied"]}','BUSINESS_UNIT','DEV_BU','READ');
        INSERT INTO kb.document_version(document_version_id,document_id,version_number,
          original_file_uri,content_type,sha256_checksum,acquired_at,extraction_status,
          validation_status,current_version_flag)
        SELECT ('35000000-0000-0000-0000-00000000000' || item.number)::uuid,
          item.document_id,1,'test://retrieval/' || item.number,'text/plain',
          repeat(item.number::text,64),now(),'COMPLETED','PASSED',false
        FROM (VALUES
          (1,'{ids["apps"]}'::uuid),(2,'{ids["fdi"]}'::uuid),
          (3,'{ids["analyst"]}'::uuid),(4,'{ids["denied"]}'::uuid)
        ) item(number,document_id);
        INSERT INTO kb.document_processing_version(processing_version_id,tenant_id,document_id,
          document_version_id,processing_number,parser_name,parser_version,chunker_name,
          chunker_version,chunking_configuration_json,chunking_configuration_hash,
          embedding_model_code,processing_status,chunk_count,embedded_chunk_count,
          validation_status,completed_at)
        SELECT ('36000000-0000-0000-0000-00000000000' || item.number)::uuid,'{TENANT_ID}',
          item.document_id,('35000000-0000-0000-0000-00000000000' || item.number)::uuid,
          1,'integration','1','semantic-structure','1','{{}}'::jsonb,
          repeat(item.number::text,64),'DEFAULT_1536','COMPLETED',1,1,'PASSED',now()
        FROM (VALUES
          (1,'{ids["apps"]}'::uuid),(2,'{ids["fdi"]}'::uuid),
          (3,'{ids["analyst"]}'::uuid),(4,'{ids["denied"]}'::uuid)
        ) item(number,document_id);
        INSERT INTO kb.document_chunk(chunk_id,document_version_id,chunk_sequence,heading_path,
          content_text,token_count,content_hash,processing_version_id,tenant_id,document_id,
          source_id,audience_code,security_classification,embedding_input_hash)
        VALUES
          ('37000000-0000-0000-0000-000000000001','35000000-0000-0000-0000-000000000001',
            1,'Payables > Holds',
            'Invoice validation holds procedure for Fusion Applications 26C.',10,
            repeat('1',64),'36000000-0000-0000-0000-000000000001','{TENANT_ID}',
            '{ids["apps"]}','31000000-0000-0000-0000-000000000001','EMPLOYEE','INTERNAL',repeat('1',64)),
          ('37000000-0000-0000-0000-000000000002','35000000-0000-0000-0000-000000000002',
            1,'FDI > Analytics','Invoice validation analytics for FDI release 26.R2.',10,
            repeat('2',64),'36000000-0000-0000-0000-000000000002','{TENANT_ID}',
            '{ids["fdi"]}','31000000-0000-0000-0000-000000000002','EMPLOYEE','PUBLIC',repeat('2',64)),
          ('37000000-0000-0000-0000-000000000003','35000000-0000-0000-0000-000000000003',
            1,'Analyst > Diagnostic','Invoice validation diagnostic for analysts only.',10,
            repeat('3',64),'36000000-0000-0000-0000-000000000003','{TENANT_ID}',
            '{ids["analyst"]}','31000000-0000-0000-0000-000000000003','ANALYST','CONFIDENTIAL',repeat('3',64)),
          ('37000000-0000-0000-0000-000000000004','35000000-0000-0000-0000-000000000004',
            1,'Privileged > Secret',
            'RESTRICTED-CANARY-991 privileged invoice secret for knowledge approvers.',10,
            repeat('4',64),'36000000-0000-0000-0000-000000000004','{TENANT_ID}',
            '{ids["denied"]}','31000000-0000-0000-0000-000000000004','EMPLOYEE','INTERNAL',repeat('4',64));
        INSERT INTO kb.chunk_embedding_1536(chunk_id,embedding_model_code,embedding,tenant_id,
          processing_version_id)
        SELECT chunk_id,'DEFAULT_1536','{vector}'::vector,'{TENANT_ID}',processing_version_id
        FROM kb.document_chunk WHERE document_id IN
          ('{ids["apps"]}','{ids["fdi"]}','{ids["analyst"]}','{ids["denied"]}');
        UPDATE kb.document_version version SET current_version_flag=true,published_at=now(),
          published_processing_version_id=processing.processing_version_id
        FROM kb.document_processing_version processing
        WHERE processing.document_version_id=version.document_version_id
          AND version.document_id IN
            ('{ids["apps"]}','{ids["fdi"]}','{ids["analyst"]}','{ids["denied"]}');
        UPDATE kb.document SET canonical_url='https://docs.example.invalid/26c/payables/holds'
          WHERE document_id='{ids["apps"]}';
        UPDATE kb.document_chunk SET section_title='Validation Holds',
          section_anchor='validation-holds',page_number=123,
          content_text='AP-810 invoice validation holds procedure for Fusion Applications 26C.'
          WHERE document_id='{ids["apps"]}';
        """
    )
    _psql(
        f"""
        INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
        VALUES ('20000000-0000-0000-0000-000000000002','RETRIEVAL_OTHER','Other tenant');
        INSERT INTO identity.app_user(user_id,tenant_id,external_subject,email_address,display_name)
        VALUES ('22000000-0000-0000-0000-000000000020',
          '20000000-0000-0000-0000-000000000002','other-owner',
          'other-owner@example.invalid','Other Owner');
        INSERT INTO kb.source(source_id,tenant_id,source_code,source_name,source_type,
          acquisition_method,canonical_location,active_flag,approval_status,owner_user_id,
          approved_by,approved_at)
        VALUES ('31000000-0000-0000-0000-000000000005',
          '20000000-0000-0000-0000-000000000002','OTHER_TENANT_RETRIEVAL',
          'Other tenant source','COMPANY_POLICY','MANUAL_UPLOAD',
          'https://other.example.invalid/knowledge',true,'APPROVED',
          '22000000-0000-0000-0000-000000000020',
          '22000000-0000-0000-0000-000000000020',now());
        INSERT INTO kb.document(document_id,tenant_id,source_id,release_id,
          external_document_key,document_title,document_type,audience_code,language_code,
          security_classification,approval_status,active_flag)
        VALUES ('{ids["other_tenant"]}','20000000-0000-0000-0000-000000000002',
          '31000000-0000-0000-0000-000000000005','{apps_release}',
          'other-tenant-invoice','Other Tenant Invoice Secret','POLICY','EMPLOYEE','en',
          'INTERNAL','APPROVED',true);
        INSERT INTO kb.document_version(document_version_id,document_id,version_number,
          original_file_uri,content_type,sha256_checksum,acquired_at,extraction_status,
          validation_status,current_version_flag)
        VALUES ('35000000-0000-0000-0000-000000000005','{ids["other_tenant"]}',1,
          'test://retrieval/other','text/plain',repeat('5',64),now(),'COMPLETED','PASSED',false);
        INSERT INTO kb.document_processing_version(processing_version_id,tenant_id,document_id,
          document_version_id,processing_number,parser_name,parser_version,chunker_name,
          chunker_version,chunking_configuration_json,chunking_configuration_hash,
          embedding_model_code,processing_status,chunk_count,embedded_chunk_count,
          validation_status,completed_at)
        VALUES ('36000000-0000-0000-0000-000000000005',
          '20000000-0000-0000-0000-000000000002','{ids["other_tenant"]}',
          '35000000-0000-0000-0000-000000000005',1,'integration','1',
          'semantic-structure','1','{{}}',repeat('5',64),'DEFAULT_1536','COMPLETED',
          1,1,'PASSED',now());
        INSERT INTO kb.document_chunk(chunk_id,document_version_id,chunk_sequence,heading_path,
          content_text,token_count,content_hash,processing_version_id,tenant_id,document_id,
          source_id,audience_code,security_classification,embedding_input_hash)
        VALUES ('37000000-0000-0000-0000-000000000005',
          '35000000-0000-0000-0000-000000000005',1,'Other > Invoice',
          'OTHER-TENANT-CANARY-992 other tenant invoice validation secret.',8,repeat('5',64),
          '36000000-0000-0000-0000-000000000005',
          '20000000-0000-0000-0000-000000000002','{ids["other_tenant"]}',
          '31000000-0000-0000-0000-000000000005','EMPLOYEE','INTERNAL',repeat('5',64));
        INSERT INTO kb.chunk_embedding_1536(chunk_id,embedding_model_code,embedding,tenant_id,
          processing_version_id)
        VALUES ('37000000-0000-0000-0000-000000000005','DEFAULT_1536','{vector}'::vector,
          '20000000-0000-0000-0000-000000000002',
          '36000000-0000-0000-0000-000000000005');
        UPDATE kb.document_version SET current_version_flag=true,published_at=now(),
          published_processing_version_id='36000000-0000-0000-0000-000000000005'
        WHERE document_version_id='35000000-0000-0000-0000-000000000005';
        """
    )
    return vector, ids


def _ensure_retrieval_corpus() -> tuple[str, dict[str, str]]:
    ids = {
        "apps": "34000000-0000-0000-0000-000000000001",
        "fdi": "34000000-0000-0000-0000-000000000002",
        "analyst": "34000000-0000-0000-0000-000000000003",
        "denied": "34000000-0000-0000-0000-000000000004",
        "other_tenant": "34000000-0000-0000-0000-000000000005",
    }
    if _value(f"SELECT count(*) FROM kb.document WHERE document_id='{ids['apps']}'") == "0":
        return _seed_retrieval_corpus()
    _psql(
        "UPDATE kb.document SET active_flag=true,next_review_date=NULL "
        f"WHERE document_id IN ('{ids['apps']}','{ids['fdi']}','{ids['analyst']}',"
        f"'{ids['denied']}')"
    )
    vector = "[1," + ",".join("0" for _ in range(1535)) + "]"
    return vector, ids


def _retrieval_context(
    role: str,
    persona: str,
    *,
    support_groups: frozenset[UUID] = frozenset(),
    business_unit_id: UUID | None = None,
) -> RequestContext:
    return RequestContext(
        tenant_id=UUID(TENANT_ID),
        user_id=UUID(AUTHOR_ID),
        external_subject=f"retrieval-{role.lower()}",
        roles=frozenset({role}),
        support_group_ids=support_groups,
        business_unit_id=business_unit_id,
        correlation_id=str(uuid4()),
        request_id=f"retrieval-{persona.lower()}",
    )


@pytest.mark.integration
def test_authorization_first_full_text_vector_filters_and_query_plans(
    application: tuple[TestClient, FastAPI, MemoryStorage],
) -> None:
    _, app, _ = application
    assert not hasattr(app.state.retrieval_service, "_cache")
    assert not hasattr(app.state.retrieval_service, "_tracer")
    vector, ids = _seed_retrieval_corpus()
    embedding = (1.0,) + (0.0,) * 1535
    customer = _retrieval_context("CUSTOMER", "EMPLOYEE")
    unfiltered_request = RetrievalRequest(
        "Invoice Validation", embedding, limit=20, persona="EMPLOYEE"
    )
    first = asyncio.run(
        _retrieve(customer, unfiltered_request), loop_factory=asyncio.SelectorEventLoop
    )
    second = asyncio.run(
        _retrieve(customer, unfiltered_request), loop_factory=asyncio.SelectorEventLoop
    )
    assert first == second
    assert {item.document_id for item in first.lexical} == {
        UUID(ids["apps"]),
        UUID(ids["fdi"]),
    }
    assert {item.document_id for item in first.vector} == {
        UUID(ids["apps"]),
        UUID(ids["fdi"]),
    }
    assert all(item.rank <= 20 for item in (*first.lexical, *first.vector))
    assert UUID(ids["analyst"]) not in {item.document_id for item in first.vector}
    assert UUID(ids["denied"]) not in {item.document_id for item in first.vector}
    assert UUID(ids["other_tenant"]) not in {item.document_id for item in first.vector}

    apps = asyncio.run(
        _retrieve(
            customer,
            RetrievalRequest(
                "Invoice Validation Holds",
                embedding,
                filters=RetrievalFilters(
                    product_codes=("FINANCIALS",),
                    module_codes=("ACCOUNTS_PAYABLE",),
                    release_families=("FUSION_APPLICATIONS",),
                    release_codes=("26C",),
                    language_codes=("en",),
                    source_ids=(UUID("31000000-0000-0000-0000-000000000001"),),
                ),
                persona="EMPLOYEE",
            ),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert {item.document_id for item in (*apps.lexical, *apps.vector)} == {UUID(ids["apps"])}
    evidence = asyncio.run(
        _retrieve_evidence(
            customer,
            "AP-810 invoice validation holds for 26C Accounts Payable",
            RetrievalFilters(
                product_codes=("FINANCIALS",),
                module_codes=("ACCOUNTS_PAYABLE",),
                release_families=("FUSION_APPLICATIONS",),
                release_codes=("26C",),
            ),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert evidence.evidence[0].document_id == UUID(ids["apps"])
    assert evidence.evidence[0].release_family == "FUSION_APPLICATIONS"
    assert evidence.evidence[0].release_code == "26C"
    assert evidence.evidence[0].module_code == "ACCOUNTS_PAYABLE"
    assert evidence.evidence[0].canonical_uri.endswith("/26c/payables/holds")
    assert evidence.evidence[0].section_anchor == "validation-holds"
    assert evidence.evidence[0].components.exact_identifier_boost > 0
    _psql(
        f"UPDATE kb.document SET next_review_date=CURRENT_DATE-1 WHERE document_id='{ids['apps']}'"
    )
    stale = asyncio.run(
        _retrieve_evidence(
            customer,
            "AP-810 invoice validation holds for 26C",
            RetrievalFilters(
                module_codes=("ACCOUNTS_PAYABLE",),
                release_families=("FUSION_APPLICATIONS",),
                release_codes=("26C",),
            ),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert stale.evidence == ()
    _psql(f"UPDATE kb.document SET next_review_date=NULL WHERE document_id='{ids['apps']}'")
    fdi = asyncio.run(
        _retrieve(
            customer,
            RetrievalRequest(
                "Invoice Validation",
                embedding,
                filters=RetrievalFilters(
                    release_families=("FUSION_DATA_INTELLIGENCE",),
                    release_codes=("26.R2",),
                ),
                persona="EMPLOYEE",
            ),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert {item.document_id for item in (*fdi.lexical, *fdi.vector)} == {UUID(ids["fdi"])}

    analyst = asyncio.run(
        _retrieve(
            _retrieval_context("AGENT", "ANALYST"),
            RetrievalRequest("Invoice Diagnostic", embedding, persona="ANALYST"),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert UUID(ids["analyst"]) in {item.document_id for item in analyst.vector}
    assert UUID(ids["denied"]) not in {item.document_id for item in analyst.vector}
    approver = asyncio.run(
        _retrieve(
            _retrieval_context("KNOWLEDGE_APPROVER", "EMPLOYEE"),
            RetrievalRequest("Privileged Invoice Secret", embedding, persona="EMPLOYEE"),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert UUID(ids["denied"]) in {item.document_id for item in approver.lexical}
    group_member = asyncio.run(
        _retrieve(
            _retrieval_context(
                "AGENT",
                "ANALYST",
                support_groups=frozenset({UUID("23000000-0000-0000-0000-000000000002")}),
            ),
            RetrievalRequest("Privileged Invoice Secret", embedding, persona="ANALYST"),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert UUID(ids["denied"]) in {item.document_id for item in group_member.lexical}
    business_unit_member = asyncio.run(
        _retrieve(
            _retrieval_context(
                "CUSTOMER",
                "EMPLOYEE",
                business_unit_id=UUID("21000000-0000-0000-0000-000000000001"),
            ),
            RetrievalRequest("Privileged Invoice Secret", embedding, persona="EMPLOYEE"),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert UUID(ids["denied"]) in {item.document_id for item in business_unit_member.lexical}

    _psql(f"UPDATE kb.document SET active_flag=false WHERE document_id='{ids['apps']}'")
    retired = asyncio.run(
        _retrieve(customer, unfiltered_request), loop_factory=asyncio.SelectorEventLoop
    )
    assert UUID(ids["apps"]) not in {item.document_id for item in retired.vector}

    lexical_plan = _value(
        "SET enable_seqscan=off; EXPLAIN (COSTS OFF) SELECT chunk_id "
        "FROM kb.document_chunk WHERE search_vector@@websearch_to_tsquery('english','invoice');"
    )
    assert "kb_document_chunk_fts_ix" in lexical_plan
    vector_plan = _value(
        "SET enable_seqscan=off; EXPLAIN (COSTS OFF) SELECT chunk_id "
        f"FROM kb.chunk_embedding_1536 ORDER BY embedding<=>'{vector}'::vector LIMIT 2;"
    )
    assert "kb_chunk_embedding_1536_hnsw_ix" in vector_plan
    assert (
        _value(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='kb' AND indexname IN ("
            "'document_permission_retrieval_ix','document_retrieval_filters_ix',"
            "'product_node_retrieval_lineage_ix','source_retrieval_active_ix')"
        )
        == "4"
    )


@pytest.mark.integration
def test_retrieval_regression_corpus_quality_acl_evidence_and_latency(
    application: tuple[TestClient, FastAPI, MemoryStorage],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del application
    _, ids = _ensure_retrieval_corpus()
    corpus = cast(
        "dict[str, Any]",
        json.loads(
            (ROOT / "tests/ai_evaluation/retrieval_regression_v1.json").read_text(encoding="utf-8")
        ),
    )
    thresholds = cast("dict[str, float]", corpus["quality_thresholds"])
    cases = cast("list[dict[str, Any]]", corpus["cases"])
    external_ids = {
        "retrieval-apps-26c": UUID(ids["apps"]),
        "retrieval-fdi-26r2": UUID(ids["fdi"]),
        "retrieval-analyst": UUID(ids["analyst"]),
        "retrieval-denied": UUID(ids["denied"]),
        "other-tenant-invoice": UUID(ids["other_tenant"]),
    }
    caplog.set_level(logging.DEBUG)
    top_hits = 0
    reciprocal_ranks: list[float] = []
    latencies_ms: list[float] = []

    for case in cases:
        raw_filters = cast("dict[str, list[str]]", case.get("filters", {}))
        filters = RetrievalFilters(
            product_codes=tuple(raw_filters.get("product_codes", [])),
            module_codes=tuple(raw_filters.get("module_codes", [])),
            release_families=tuple(raw_filters.get("release_families", [])),
            release_codes=tuple(raw_filters.get("release_codes", [])),
            language_codes=tuple(raw_filters.get("language_codes", [])),
            source_ids=tuple(UUID(value) for value in raw_filters.get("source_ids", [])),
        )
        context = _retrieval_context(str(case["role"]), str(case["persona"]))
        started = time.perf_counter()
        evidence = asyncio.run(
            _retrieve_evidence(
                context,
                str(case["query"]),
                filters,
                persona=str(case["persona"]),
            ),
            loop_factory=asyncio.SelectorEventLoop,
        )
        latencies_ms.append((time.perf_counter() - started) * 1000)
        replay = asyncio.run(
            _retrieve_evidence(
                context,
                str(case["query"]),
                filters,
                persona=str(case["persona"]),
            ),
            loop_factory=asyncio.SelectorEventLoop,
        )
        assert replay == evidence, case["case_id"]
        document_ids = [item.document_id for item in evidence.evidence]
        forbidden = {
            external_ids[key] for key in cast("list[str]", case["forbidden_external_keys"])
        }
        assert forbidden.isdisjoint(document_ids), case["case_id"]
        if case.get("expected_empty"):
            assert evidence.evidence == (), case["case_id"]
        if case["case_id"] == "fusion-apps-26c-ap-error":
            assert evidence.evidence[0].components.exact_identifier_boost > 0
        expected_key = case.get("expected_top_document_reference")
        if expected_key is not None:
            expected = external_ids[str(expected_key)]
            assert expected in document_ids, case["case_id"]
            rank = document_ids.index(expected) + 1
            reciprocal_ranks.append(1 / rank)
            top_hits += int(rank == 1)
        assert [item.rank for item in evidence.evidence] == list(
            range(1, len(evidence.evidence) + 1)
        )
        assert len({item.chunk_id for item in evidence.evidence}) == len(evidence.evidence)
        for item in evidence.evidence:
            row = _value(
                "SELECT concat_ws('|',document.document_id,version.document_version_id,"
                "chunk.chunk_id,COALESCE(document.canonical_url,source.canonical_location),"
                "COALESCE(release.release_family,''),COALESCE(release.release_code,'')) "
                "FROM kb.document_chunk chunk "
                "JOIN kb.document_version version "
                "ON version.document_version_id=chunk.document_version_id "
                "JOIN kb.document document ON document.document_id=version.document_id "
                "JOIN kb.source source ON source.source_id=document.source_id "
                "LEFT JOIN kb.release release ON release.release_id=document.release_id "
                f"WHERE chunk.chunk_id='{item.chunk_id}'"
            ).split("|")
            assert row == [
                str(item.document_id),
                str(item.document_version_id),
                str(item.chunk_id),
                item.canonical_uri,
                item.release_family or "",
                item.release_code or "",
            ]

    assert top_hits / len(reciprocal_ranks) >= thresholds["minimum_top_1_accuracy"]
    assert (
        sum(reciprocal_ranks) / len(reciprocal_ranks) >= thresholds["minimum_mean_reciprocal_rank"]
    )
    ordered_latency = sorted(latencies_ms)
    p95_index = math.ceil(len(ordered_latency) * 0.95) - 1
    assert ordered_latency[p95_index] <= thresholds["maximum_warm_p95_latency_ms"]

    restricted_chunk = "37000000-0000-0000-0000-000000000004"
    other_tenant_chunk = "37000000-0000-0000-0000-000000000005"
    intermediate = asyncio.run(
        _retrieve(
            _retrieval_context("CUSTOMER", "EMPLOYEE"),
            RetrievalRequest(
                "RESTRICTED-CANARY-991 OTHER-TENANT-CANARY-992",
                (1.0,) + (0.0,) * 1535,
                persona="EMPLOYEE",
            ),
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    intermediate_documents = {
        item.document_id for item in (*intermediate.lexical, *intermediate.vector)
    }
    assert UUID(ids["denied"]) not in intermediate_documents
    assert UUID(ids["other_tenant"]) not in intermediate_documents
    captured = caplog.text
    assert "RESTRICTED-CANARY-991" not in captured
    assert "OTHER-TENANT-CANARY-992" not in captured
    assert restricted_chunk not in captured
    assert other_tenant_chunk not in captured

    customer = _retrieval_context("CUSTOMER", "EMPLOYEE")
    application_filters = RetrievalFilters(
        module_codes=("ACCOUNTS_PAYABLE",),
        release_families=("FUSION_APPLICATIONS",),
        release_codes=("26C",),
    )
    _psql(
        f"UPDATE kb.document SET next_review_date=CURRENT_DATE-1 WHERE document_id='{ids['apps']}'"
    )
    stale = asyncio.run(
        _retrieve_evidence(customer, "AP-810 invoice validation holds", application_filters),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert stale.evidence == ()
    _psql(
        f"UPDATE kb.document SET next_review_date=NULL,active_flag=false "
        f"WHERE document_id='{ids['apps']}'"
    )
    retired = asyncio.run(
        _retrieve_evidence(customer, "AP-810 invoice validation holds", application_filters),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert retired.evidence == ()
    _psql(f"UPDATE kb.document SET active_flag=true WHERE document_id='{ids['apps']}'")
