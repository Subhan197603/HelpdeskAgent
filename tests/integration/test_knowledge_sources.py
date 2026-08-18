"""PostgreSQL coverage for governed knowledge-source administration."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-knowledge-source-test"
PORT = "55455"
DATABASE = "knowledge_source_test"
TENANT_ID = "20000000-0000-0000-0000-000000000001"
AUTHOR_ID = "22000000-0000-0000-0000-000000000007"
OTHER_TENANT_ID = "20000000-0000-0000-0000-000000000099"
OTHER_USER_ID = "22000000-0000-0000-0000-000000000099"
OTHER_SOURCE_ID = "25000000-0000-0000-0000-000000000099"


class HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


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
def knowledge_database() -> Iterator[None]:
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
        _psql(
            "INSERT INTO kb.product_node(product_node_id,parent_product_node_id,product_code,"
            "product_name,product_level,release_family) SELECT "
            "'24000000-0000-0000-0000-000000000001',product_node_id,'PAYABLES',"
            "'Payables','MODULE','FUSION_APPLICATIONS' FROM kb.product_node "
            "WHERE product_code='FINANCIALS'"
        )
        _psql(
            "INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name) VALUES "
            f"('{OTHER_TENANT_ID}','OTHER_KB','Other knowledge tenant');"
            "INSERT INTO identity.app_user(user_id,tenant_id,external_subject,email_address,"
            "display_name) VALUES "
            f"('{OTHER_USER_ID}','{OTHER_TENANT_ID}','other-kb-owner',"
            "'other-kb-owner@example.invalid','Other knowledge owner');"
            "INSERT INTO kb.source(source_id,tenant_id,source_code,source_name,source_type,"
            "canonical_location,acquisition_method,active_flag,audience_scope,source_status,"
            "approval_status,owner_user_id,created_by,updated_by) VALUES "
            f"('{OTHER_SOURCE_ID}','{OTHER_TENANT_ID}','OTHER_PRIVATE','Other private source',"
            "'INTERNAL_KNOWLEDGE','manual:other-private','MANUAL_UPLOAD',true,'RESTRICTED',"
            f"'ACTIVE','DRAFT','{OTHER_USER_ID}','{OTHER_USER_ID}','{OTHER_USER_ID}')"
        )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    settings = Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": (f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"),
            "developer_identity_enabled": True,
            "object_storage_enabled": False,
            "rls_enabled": True,
            "trusted_hosts": ["testserver"],
        }
    )
    resources = ApplicationResources(
        Database(settings), HealthyProbe(), HealthyProbe(), HealthyProbe()
    )
    with TestClient(
        create_app(settings, resource_factory=lambda _: resources),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as test_client:
        yield test_client


def _headers(persona: str, key: str | None = None) -> dict[str, str]:
    headers = {"X-Developer-User": f"DEV/{persona}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _metadata() -> tuple[str, str, str]:
    product_id = _value(
        "SELECT product_node_id FROM kb.product_node WHERE product_code='FINANCIALS' LIMIT 1"
    )
    module_id = _value(
        "SELECT product_node_id FROM kb.product_node "
        "WHERE product_level='MODULE' AND release_family='FUSION_APPLICATIONS' LIMIT 1"
    )
    release_id = _value(
        "SELECT release_id FROM kb.release "
        "WHERE release_family='FUSION_APPLICATIONS' AND release_code='26C'"
    )
    return product_id, module_id, release_id


def _source_payload(*, code: str, source_type: str = "COMPANY_POLICY") -> dict[str, Any]:
    product_id, module_id, release_id = _metadata()
    return {
        "code": code,
        "name": f"Governed source {code}",
        "source_type": source_type,
        "publisher_name": "Example Corporation",
        "canonical_location": (
            "https://docs.oracle.com/fusion/26c/"
            if source_type == "ORACLE_PUBLIC_DOCUMENTATION"
            else f"repository:knowledge/{code.lower()}"
        ),
        "acquisition_method": "REPOSITORY_CONNECTOR",
        "permission_reference": "governance-record-001",
        "audience_scope": "ANALYST",
        "status": "ACTIVE",
        "owner_user_id": AUTHOR_ID,
        "product_node_id": product_id,
        "module_node_id": module_id,
        "release_id": release_id,
        "language_code": "en-GB",
        "scope": "TENANT",
    }


@pytest.mark.integration
def test_employee_cannot_administer_sources(client: TestClient) -> None:
    assert (
        client.get("/api/v1/admin/knowledge/sources", headers=_headers("customer")).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/admin/knowledge/sources",
            headers=_headers("customer", "employee-source-create"),
            json=_source_payload(code="EMPLOYEE_DENIED"),
        ).status_code
        == 403
    )


@pytest.mark.integration
def test_tenant_source_is_not_visible_to_another_tenant(client: TestClient) -> None:
    response = client.get(
        f"/api/v1/admin/knowledge/sources/{OTHER_SOURCE_ID}",
        headers=_headers("platform-admin"),
    )
    assert response.status_code == 404
    listing = client.get("/api/v1/admin/knowledge/sources", headers=_headers("platform-admin"))
    assert listing.status_code == 200
    assert "OTHER_PRIVATE" not in {item["code"] for item in listing.json()["items"]}


@pytest.mark.integration
def test_registry_lifecycle_metadata_approval_and_audit(client: TestClient) -> None:
    body = _source_payload(code="INTERNAL_RUNBOOKS")
    created = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", "create-internal-runbooks"),
        json=body,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["approval_status"] == "DRAFT"
    assert source["automated_access_allowed"] is False
    assert source["audience_scope"] == "ANALYST"
    assert source["release_family"] == "FUSION_APPLICATIONS"
    assert source["release_code"] == "26C"
    assert source["language_code"] == "en-GB"

    replay = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", "create-internal-runbooks"),
        json=body,
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["id"] == source["id"]
    duplicate = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", "create-duplicate-source-code"),
        json=body,
    )
    assert duplicate.status_code == 409

    permission = client.get(
        f"/api/v1/admin/knowledge/sources/{source['id']}/acquisition-permission",
        headers=_headers("platform-admin"),
    )
    assert permission.status_code == 200
    assert permission.json()["allowed"] is False
    assert "SOURCE_NOT_APPROVED" in permission.json()["reasons"]

    approved = client.post(
        f"/api/v1/admin/knowledge/sources/{source['id']}/approval-decisions",
        headers=_headers("platform-admin", "approve-internal-runbooks"),
        json={"decision": "APPROVED", "expected_version": 1},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "APPROVED"
    assert approved.json()["row_version"] == 2

    authorized = client.post(
        f"/api/v1/admin/knowledge/sources/{source['id']}/acquisition-authorizations",
        headers=_headers("platform-admin", "authorize-internal-runbooks"),
        json={
            "decision": "APPROVED",
            "acquisition_method": "REPOSITORY_CONNECTOR",
            "permission_reference": "change-approval-4321",
            "expected_version": 2,
        },
    )
    assert authorized.status_code == 201, authorized.text
    assert authorized.json()["source"]["row_version"] == 3
    assert authorized.json()["source"]["automated_access_allowed"] is True

    allowed = client.get(
        f"/api/v1/admin/knowledge/sources/{source['id']}/acquisition-permission",
        headers=_headers("platform-admin"),
    )
    assert allowed.json()["allowed"] is True

    update = body | {"expected_version": 3, "status": "RETIRED"}
    update.pop("scope")
    retired = client.put(
        f"/api/v1/admin/knowledge/sources/{source['id']}",
        headers=_headers("knowledge-author", "retire-internal-runbooks"),
        json=update,
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "RETIRED"
    assert retired.json()["approval_status"] == "DRAFT"
    assert retired.json()["automated_access_allowed"] is False

    assert (
        _value(
            "SELECT count(*) FROM audit.audit_event WHERE resource_id="
            f"'{source['id']}' AND action_code LIKE 'KNOWLEDGE_SOURCE_%'"
        )
        == "4"
    )
    assert (
        _value(
            "SELECT count(*) FROM kb.source_acquisition_authorization WHERE source_id="
            f"'{source['id']}'"
        )
        == "1"
    )
    immutable = _psql(
        "UPDATE kb.source_acquisition_authorization SET decision_code='REVOKED' WHERE source_id="
        f"'{source['id']}'",
        check=False,
    )
    assert immutable.returncode != 0


@pytest.mark.integration
def test_oracle_acquisition_stays_disabled_without_runtime_permission(client: TestClient) -> None:
    body = _source_payload(code="ORACLE_26C_TEST", source_type="ORACLE_PUBLIC_DOCUMENTATION")
    created = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", "create-oracle-test"),
        json=body,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    approved = client.post(
        f"/api/v1/admin/knowledge/sources/{source['id']}/approval-decisions",
        headers=_headers("platform-admin", "approve-oracle-test"),
        json={"decision": "APPROVED", "expected_version": 1},
    )
    assert approved.status_code == 200
    authorized = client.post(
        f"/api/v1/admin/knowledge/sources/{source['id']}/acquisition-authorizations",
        headers=_headers("platform-admin", "authorize-oracle-test"),
        json={
            "decision": "APPROVED",
            "acquisition_method": "REPOSITORY_CONNECTOR",
            "permission_reference": "oracle-license-review-19",
            "expected_version": 2,
        },
    )
    assert authorized.status_code == 201
    permission = client.get(
        f"/api/v1/admin/knowledge/sources/{source['id']}/acquisition-permission",
        headers=_headers("platform-admin"),
    ).json()
    assert permission["allowed"] is False
    assert permission["reasons"] == ["ORACLE_AUTOMATED_ACQUISITION_DISABLED"]


@pytest.mark.integration
def test_canonical_location_and_global_scope_are_fail_closed(client: TestClient) -> None:
    unsafe = _source_payload(code="UNSAFE_LOCATION")
    unsafe["canonical_location"] = "https://user:secret@example.invalid/file?token=secret"
    assert (
        client.post(
            "/api/v1/admin/knowledge/sources",
            headers=_headers("knowledge-author", "unsafe-source-location"),
            json=unsafe,
        ).status_code
        == 422
    )

    global_source = _source_payload(code="GLOBAL_DENIED")
    global_source["scope"] = "GLOBAL"
    assert (
        client.post(
            "/api/v1/admin/knowledge/sources",
            headers=_headers("knowledge-author", "global-source-denied"),
            json=global_source,
        ).status_code
        == 403
    )


@pytest.mark.integration
def test_refresh_lifecycle_migration_is_minimal_and_backfilled() -> None:
    assert _value("SELECT version_num FROM config.alembic_version") == "0035_chunk_error_codes"
    assert (
        _value(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='kb' AND table_name='source' AND column_name IN "
            "('refresh_state','refresh_due_at','last_refresh_requested_at',"
            "'last_refresh_requested_by','last_refresh_completed_at')"
        )
        == "5"
    )
    assert (
        _value("SELECT count(*) FROM pg_constraint WHERE conname='kb_source_refresh_state_ck'")
        == "1"
    )
    assert (
        _value("SELECT count(*) FROM pg_indexes WHERE indexname='kb_source_refresh_lifecycle_ix'")
        == "1"
    )
    assert (
        _value(
            "SELECT count(*) FROM kb.source WHERE refresh_state IS DISTINCT FROM "
            "'CURRENT' AND source_id='" + OTHER_SOURCE_ID + "'"
        )
        == "0"
    )
    assert _value("SELECT has_table_privilege('helpdesk_app','kb.source','UPDATE')") == "t"
    assert _value("SELECT has_table_privilege('helpdesk_app','kb.source','DELETE')") == "f"


@pytest.mark.integration
def test_refresh_lifecycle_administration_is_governed(client: TestClient) -> None:
    created = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", "create-refresh-lifecycle"),
        json=_source_payload(code="REFRESH_LIFECYCLE"),
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["refresh_state"] == "CURRENT"
    assert source["effective_refresh_state"] == "CURRENT"
    assert source["last_acquisition_status"] is None
    runs_before = _value("SELECT count(*) FROM kb.ingestion_run")

    lifecycle_url = f"/api/v1/admin/knowledge/sources/{source['id']}/refresh-lifecycle"
    assert (
        client.post(
            lifecycle_url,
            headers=_headers("customer", "employee-refresh-denied"),
            json={"action": "MARK_REFRESH_DUE", "expected_version": 1},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/admin/knowledge/sources/{OTHER_SOURCE_ID}/refresh-lifecycle",
            headers=_headers("knowledge-author", "cross-tenant-refresh-denied"),
            json={"action": "MARK_REFRESH_DUE", "expected_version": 1},
        ).status_code
        == 404
    )

    marked = client.post(
        lifecycle_url,
        headers=_headers("knowledge-author", "mark-refresh-due"),
        json={"action": "MARK_REFRESH_DUE", "expected_version": 1},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["refresh_state"] == "REFRESH_DUE"
    assert marked.json()["effective_refresh_state"] == "REFRESH_DUE"
    assert marked.json()["refresh_due_at"] is not None
    assert marked.json()["last_refresh_requested_at"] is not None
    assert marked.json()["row_version"] == 2

    replay = client.post(
        lifecycle_url,
        headers=_headers("knowledge-author", "mark-refresh-due"),
        json={"action": "MARK_REFRESH_DUE", "expected_version": 1},
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["row_version"] == 2

    invalid = client.post(
        lifecycle_url,
        headers=_headers("knowledge-author", "mark-refresh-due-invalid"),
        json={"action": "MARK_REFRESH_DUE", "expected_version": 2},
    )
    assert invalid.status_code == 409
    assert invalid.json()["type"].endswith("/problems/invalid_transition")

    stale = client.post(
        lifecycle_url,
        headers=_headers("knowledge-author", "mark-current-stale-version"),
        json={"action": "MARK_CURRENT", "expected_version": 1},
    )
    assert stale.status_code == 409

    completed = client.post(
        lifecycle_url,
        headers=_headers("knowledge-author", "mark-current"),
        json={"action": "MARK_CURRENT", "expected_version": 2},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["refresh_state"] == "CURRENT"
    assert completed.json()["refresh_due_at"] is None
    assert completed.json()["last_refresh_completed_at"] is not None

    listing = client.get(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author"),
        params={"refresh_state": "REFRESH_DUE"},
    )
    assert listing.status_code == 200
    assert "REFRESH_LIFECYCLE" not in {item["code"] for item in listing.json()["items"]}
    paged = client.get(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author"),
        params={"search": "REFRESH_LIFECYCLE", "limit": 1},
    )
    assert paged.status_code == 200
    assert paged.json()["total"] >= 1
    assert paged.json()["items"][0]["code"] == "REFRESH_LIFECYCLE"

    retire = _source_payload(code="REFRESH_LIFECYCLE") | {
        "expected_version": 3,
        "status": "RETIRED",
    }
    retire.pop("scope")
    retired = client.put(
        f"/api/v1/admin/knowledge/sources/{source['id']}",
        headers=_headers("knowledge-author", "retire-refresh-lifecycle"),
        json=retire,
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["effective_refresh_state"] == "RETIRED"
    assert (
        client.post(
            lifecycle_url,
            headers=_headers("knowledge-author", "retired-refresh-denied"),
            json={"action": "MARK_REFRESH_DUE", "expected_version": 4},
        ).status_code
        == 409
    )

    assert _value("SELECT count(*) FROM kb.ingestion_run") == runs_before
    assert (
        _value(
            "SELECT count(*) FROM audit.audit_event WHERE resource_id="
            f"'{source['id']}' AND action_code='KNOWLEDGE_SOURCE_REFRESH_LIFECYCLE_CHANGED'"
        )
        == "2"
    )


@pytest.mark.integration
def test_content_change_migration_is_minimal_and_privileged() -> None:
    assert (
        _value(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='kb' AND table_name='ingestion_run_item' AND column_name IN "
            "('change_classification','previous_sha256','redirect_target_url',"
            "'observed_http_status')"
        )
        == "4"
    )
    for constraint in (
        "ingestion_item_change_classification_ck",
        "ingestion_item_previous_sha256_ck",
        "ingestion_item_http_status_ck",
    ):
        assert _value(f"SELECT count(*) FROM pg_constraint WHERE conname='{constraint}'") == "1", (
            constraint
        )
    status_definition = _value(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname='ingestion_item_status_ck'"
    )
    assert "SKIPPED_REMOVED" in status_definition
    assert "SKIPPED_REDIRECTED" in status_definition
    run_type_definition = _value(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ingestion_run_type_ck'"
    )
    assert "REFRESH" in run_type_definition
    for column, expected in (
        ("refresh_state", "t"),
        ("refresh_due_at", "t"),
        ("last_refresh_completed_at", "t"),
        ("source_code", "f"),
        ("approval_status", "f"),
    ):
        assert (
            _value(
                f"SELECT has_column_privilege('helpdesk_worker','kb.source','{column}','UPDATE')"
            )
            == expected
        ), column
    assert _value("SELECT has_table_privilege('helpdesk_worker','kb.source','DELETE')") == "f"


@pytest.mark.integration
def test_corpus_validation_migration_is_minimal_and_privileged() -> None:
    for table in ("corpus_validation_run", "corpus_validation_finding"):
        assert (
            _value(
                "SELECT count(*) FROM information_schema.tables "
                f"WHERE table_schema='kb' AND table_name='{table}'"
            )
            == "1"
        ), table
        assert (
            _value("SELECT relrowsecurity FROM pg_class WHERE oid='kb." + table + "'::regclass")
            == "t"
        ), table
    assert (
        _value(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='kb' "
            "AND table_name='document_chunk' AND column_name='near_duplicate_suppressed_flag'"
        )
        == "1"
    )
    assert (
        _value(
            "SELECT count(*) FROM pg_trigger WHERE tgname='immutable_kb_corpus_validation_finding'"
        )
        == "1"
    )
    assert (
        _value("SELECT has_table_privilege('helpdesk_app','kb.corpus_validation_run','UPDATE')")
        == "t"
    )
    for privilege in ("UPDATE", "DELETE"):
        assert (
            _value(
                "SELECT has_table_privilege('helpdesk_app',"
                f"'kb.corpus_validation_finding','{privilege}')"
            )
            == "f"
        ), privilege
    assert (
        _value(
            "SELECT has_column_privilege('helpdesk_app','kb.document_chunk',"
            "'near_duplicate_suppressed_flag','UPDATE')"
        )
        == "t"
    )
    assert (
        _value(
            "SELECT has_column_privilege('helpdesk_app','kb.document_chunk',"
            "'content_text','UPDATE')"
        )
        == "f"
    )
    assert (
        _value("SELECT has_table_privilege('helpdesk_worker','kb.corpus_validation_run','INSERT')")
        == "f"
    )


@pytest.mark.integration
def test_corpus_publication_migration_is_minimal_and_privileged() -> None:
    for table in ("corpus_version", "corpus_version_suppressed_chunk", "corpus_publication_event"):
        assert (
            _value(
                "SELECT count(*) FROM information_schema.tables "
                f"WHERE table_schema='kb' AND table_name='{table}'"
            )
            == "1"
        ), table
        assert (
            _value("SELECT relrowsecurity FROM pg_class WHERE oid='kb." + table + "'::regclass")
            == "t"
        ), table
    assert (
        _value(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='kb' "
            "AND indexname='corpus_version_single_active_ux'"
        )
        == "1"
    )
    for trigger in (
        "immutable_kb_corpus_version_suppressed_chunk",
        "immutable_kb_corpus_publication_event",
    ):
        assert _value(f"SELECT count(*) FROM pg_trigger WHERE tgname='{trigger}'") == "1", trigger
    assert _value("SELECT has_table_privilege('helpdesk_app','kb.corpus_version','UPDATE')") == "t"
    for table in ("corpus_version_suppressed_chunk", "corpus_publication_event"):
        for privilege in ("UPDATE", "DELETE"):
            assert (
                _value(f"SELECT has_table_privilege('helpdesk_app','kb.{table}','{privilege}')")
                == "f"
            ), (table, privilege)
    assert (
        _value("SELECT has_table_privilege('helpdesk_worker','kb.corpus_version','INSERT')") == "f"
    )
    assert (
        _value(
            "SELECT pg_get_viewdef('kb.v_active_document_chunk'::regclass) "
            "LIKE '%corpus_version_suppressed_chunk%'"
        )
        == "t"
    )


@pytest.mark.integration
def test_refresh_run_creation_and_change_report_are_governed(client: TestClient) -> None:
    created = client.post(
        "/api/v1/admin/knowledge/sources",
        headers=_headers("knowledge-author", "create-change-detection"),
        json=_source_payload(code="CHANGE_DETECTION"),
    )
    assert created.status_code == 201, created.text
    source = created.json()
    refresh_runs_url = f"/api/v1/admin/knowledge/sources/{source['id']}/refresh-runs"
    report_url = f"/api/v1/admin/knowledge/sources/{source['id']}/change-report"

    assert (
        client.post(
            refresh_runs_url,
            headers=_headers("customer", "employee-refresh-run-denied"),
            json={"expected_version": 1},
        ).status_code
        == 403
    )
    assert client.get(report_url, headers=_headers("customer")).status_code == 403
    assert (
        client.post(
            f"/api/v1/admin/knowledge/sources/{OTHER_SOURCE_ID}/refresh-runs",
            headers=_headers("knowledge-author", "cross-tenant-refresh-run"),
            json={"expected_version": 1},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/admin/knowledge/sources/{OTHER_SOURCE_ID}/change-report",
            headers=_headers("knowledge-author"),
        ).status_code
        == 404
    )

    no_entries = client.post(
        refresh_runs_url,
        headers=_headers("knowledge-author", "refresh-run-no-entries"),
        json={"expected_version": 1},
    )
    assert no_entries.status_code == 409, no_entries.text
    assert no_entries.json()["type"].endswith("/problems/conflict")

    empty_report = client.get(report_url, headers=_headers("knowledge-author"))
    assert empty_report.status_code == 200, empty_report.text
    assert empty_report.json()["run_id"] is None
    assert empty_report.json()["pages"] == []

    retire = _source_payload(code="CHANGE_DETECTION") | {
        "expected_version": 1,
        "status": "RETIRED",
    }
    retire.pop("scope")
    retired = client.put(
        f"/api/v1/admin/knowledge/sources/{source['id']}",
        headers=_headers("knowledge-author", "retire-change-detection"),
        json=retire,
    )
    assert retired.status_code == 200, retired.text
    retired_run = client.post(
        refresh_runs_url,
        headers=_headers("knowledge-author", "refresh-run-retired"),
        json={"expected_version": 2},
    )
    assert retired_run.status_code == 409
    assert retired_run.json()["type"].endswith("/problems/invalid_transition")
    assert _value("SELECT count(*) FROM kb.ingestion_run WHERE run_type='REFRESH'") == "0"
