"""PostgreSQL validation for the knowledge article reader (Task 11.4).

Seeds a published corpus across audiences, classifications, and ACLs, then
verifies the persona eligibility matrix, section assembly, tenant isolation,
and the two-statement budgets of the list and detail reads.
"""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.knowledge.reader_repository import KnowledgeReaderRepository
from apps.api.app.retrieval.repository import RetrievalPrincipal

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-knowledge-reader-test"
PORT = "55465"
DATABASE = "knowledge_reader_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
USER_ID = UUID("22000000-0000-0000-0000-000000000004")
SOURCE_ID = UUID("90000000-0000-0000-0000-000000000001")
DOC_EMPLOYEE = UUID("91000000-0000-0000-0000-000000000001")
DOC_ANALYST = UUID("91000000-0000-0000-0000-000000000002")
DOC_RESTRICTED = UUID("91000000-0000-0000-0000-000000000003")
DOC_DRAFT = UUID("91000000-0000-0000-0000-000000000004")


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


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


def _migrate(*arguments: str) -> None:
    environment = _environment()
    environment["MIGRATION_DATABASE_URL"] = (
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
    )
    result = subprocess.run(
        ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", *arguments],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module", autouse=True)
def knowledge_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            command = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                command += ["-v", "app_password=helpdesk"]
            _compose(*command, "-U", "postgres", "-d", DATABASE, "-f", file)
        _migrate("stamp")
        _migrate("upgrade")
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
            "/development/identity_personas.sql",
        )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _principal(persona: str, tenant_id: UUID = TENANT_ID) -> RetrievalPrincipal:
    analyst = persona == "ANALYST"
    return RetrievalPrincipal(
        tenant_id=tenant_id,
        user_id=USER_ID,
        role_codes=("AGENT",) if analyst else ("CUSTOMER",),
        support_group_codes=(),
        business_unit_code=None,
        audience_codes=(
            ("ALL", "EMPLOYEE", "ANALYST", "TECHNICAL_SPECIALIST")
            if analyst
            else ("ALL", "EMPLOYEE")
        ),
        security_levels=(
            ("PUBLIC", "INTERNAL", "CONFIDENTIAL") if analyst else ("PUBLIC", "INTERNAL")
        ),
        persona=persona,
    )


async def _publish_document(
    session: object,
    document_id: UUID,
    title: str,
    document_type: str,
    audience: str,
    security: str,
    chunks: list[tuple[str, str]],
) -> None:
    version_id = uuid4()
    processing_id = uuid4()
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.document(
              document_id,tenant_id,source_id,document_title,document_type,
              audience_code,language_code,security_classification,approval_status,
              approved_by,approved_at,canonical_url)
            VALUES (:document_id,:tenant_id,:source_id,:title,:document_type,
              :audience,'en',:security,'APPROVED',:user_id,now(),
              'https://kb.example.test/' || :document_id)
            ON CONFLICT (document_id) DO NOTHING
        """),
        {
            "document_id": document_id,
            "tenant_id": TENANT_ID,
            "source_id": SOURCE_ID,
            "title": title,
            "document_type": document_type,
            "audience": audience,
            "security": security,
            "user_id": USER_ID,
        },
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.document_version(
              document_version_id,document_id,version_number,original_file_uri,
              content_type,sha256_checksum,acquired_at,extraction_status,
              validation_status,current_version_flag)
            VALUES (:version_id,:document_id,1,'file:///seed','text/markdown',
              repeat('b',64),now(),'COMPLETED','PASSED',false)
        """),
        {"version_id": version_id, "document_id": document_id},
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.document_processing_version(
              processing_version_id,tenant_id,document_id,document_version_id,
              processing_number,parser_name,parser_version,chunker_name,
              chunker_version,chunking_configuration_json,
              chunking_configuration_hash,embedding_model_code,processing_status,
              validation_status,chunk_count,embedded_chunk_count,completed_at)
            VALUES (:processing_id,:tenant_id,:document_id,:version_id,1,
              'seed-parser','1','seed-chunker','1','{}',repeat('c',64),
              'DEFAULT_1536','COMPLETED','PASSED',:chunk_count,0,now())
        """),
        {
            "processing_id": processing_id,
            "tenant_id": TENANT_ID,
            "document_id": document_id,
            "version_id": version_id,
            "chunk_count": len(chunks),
        },
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            UPDATE kb.document_version
            SET current_version_flag=true,
              published_processing_version_id=:processing_id,published_at=now()
            WHERE document_version_id=:version_id
        """),
        {"processing_id": processing_id, "version_id": version_id},
    )
    for sequence, (section_title, content) in enumerate(chunks, start=1):
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO kb.document_chunk(
                  chunk_id,document_version_id,chunk_sequence,heading_path,
                  section_title,section_anchor,page_number,content_text,
                  content_hash,processing_version_id,tenant_id,document_id,
                  source_id,audience_code,security_classification,
                  embedding_input_hash)
                VALUES (:chunk_id,:version_id,:sequence,:section_title,
                  :section_title,:anchor,:sequence,:content,
                  :content_hash,:processing_id,:tenant_id,:document_id,
                  :source_id,:audience,:security,:embedding_hash)
            """),
            {
                "chunk_id": uuid4(),
                "version_id": version_id,
                "sequence": sequence,
                "section_title": section_title,
                "anchor": f"section-{sequence}",
                "content": content,
                "content_hash": f"{sequence:064x}",
                "processing_id": processing_id,
                "tenant_id": TENANT_ID,
                "document_id": document_id,
                "source_id": SOURCE_ID,
                "audience": audience,
                "security": security,
                "embedding_hash": f"{sequence:064x}",
            },
        )


async def _seed(session: object) -> None:
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.embedding_model(
              embedding_model_code,provider_name,model_name,vector_dimension)
            VALUES ('DEFAULT_1536','local','deterministic',1536)
            ON CONFLICT (embedding_model_code) DO NOTHING
        """)
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.source(
              source_id,tenant_id,source_code,source_name,source_type,
              acquisition_method,canonical_location,audience_scope,source_status,
              approval_status,approved_by,approved_at,owner_user_id)
            VALUES (:source_id,:tenant_id,'SEED_HANDBOOK','IT Handbook',
              'INTERNAL_KNOWLEDGE','MANUAL_UPLOAD','https://kb.example.test',
              'EMPLOYEE','ACTIVE','APPROVED',:user_id,now(),:user_id)
            ON CONFLICT (source_id) DO NOTHING
        """),
        {"source_id": SOURCE_ID, "tenant_id": TENANT_ID, "user_id": USER_ID},
    )
    await _publish_document(
        session,
        DOC_EMPLOYEE,
        "Password reset FAQ",
        "FAQ",
        "EMPLOYEE",
        "INTERNAL",
        [
            ("Overview", "Passwords expire every 90 days across Fusion."),
            ("Steps", "Use the self-service portal to reset your password."),
        ],
    )
    await _publish_document(
        session,
        DOC_ANALYST,
        "Invoice validation runbook",
        "RUNBOOK",
        "ANALYST",
        "CONFIDENTIAL",
        [("Diagnosis", "Check the invoice validation service queue depth.")],
    )
    await _publish_document(
        session,
        DOC_RESTRICTED,
        "Restricted procedure",
        "PROCEDURE",
        "EMPLOYEE",
        "INTERNAL",
        [("Body", "Visible only to a specific support group.")],
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.document_permission(
              document_id,principal_type,principal_code,permission_code)
            VALUES (:document_id,'SUPPORT_GROUP','SOME_OTHER_GROUP','READ')
            ON CONFLICT DO NOTHING
        """),
        {"document_id": DOC_RESTRICTED},
    )
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO kb.document(
              document_id,tenant_id,source_id,document_title,document_type,
              audience_code,language_code,security_classification,approval_status)
            VALUES (:document_id,:tenant_id,:source_id,'Unpublished draft','FAQ',
              'EMPLOYEE','en','INTERNAL','DRAFT')
            ON CONFLICT (document_id) DO NOTHING
        """),
        {"document_id": DOC_DRAFT, "tenant_id": TENANT_ID, "source_id": SOURCE_ID},
    )
    await session.commit()  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.anyio
async def test_reader_eligibility_sections_and_statement_budget() -> None:
    engine: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn: object, cursor: object, sql: str, *args: object) -> None:
        statements.append(sql)

    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await _seed(session)
        async with maker() as session:
            repository = KnowledgeReaderRepository(session)

            statements.clear()
            employee_rows = await repository.articles(_principal("EMPLOYEE"), None, 21, 0)
            employee_facets = await repository.facets(_principal("EMPLOYEE"))
            assert len(statements) == 2, "list endpoint budget is two statements"

            employee_ids = {row.document_id for row in employee_rows}
            assert employee_ids == {DOC_EMPLOYEE}
            assert {facet.document_type: facet.count for facet in employee_facets} == {"FAQ": 1}
            faq = next(row for row in employee_rows if row.document_id == DOC_EMPLOYEE)
            assert faq.excerpt is not None
            assert faq.excerpt.startswith("Passwords expire every 90 days")
            assert faq.source_name == "IT Handbook"
            assert faq.published_at is not None

            analyst_rows = await repository.articles(_principal("ANALYST"), None, 21, 0)
            analyst_ids = {row.document_id for row in analyst_rows}
            assert analyst_ids == {DOC_EMPLOYEE, DOC_ANALYST}
            analyst_facets = await repository.facets(_principal("ANALYST"))
            assert {facet.document_type: facet.count for facet in analyst_facets} == {
                "FAQ": 1,
                "RUNBOOK": 1,
            }

            filtered = await repository.articles(_principal("ANALYST"), "RUNBOOK", 21, 0)
            assert [row.document_id for row in filtered] == [DOC_ANALYST]

            assert await repository.article(_principal("EMPLOYEE"), DOC_ANALYST) is None
            assert await repository.article(_principal("EMPLOYEE"), DOC_RESTRICTED) is None
            assert await repository.article(_principal("ANALYST"), DOC_RESTRICTED) is None
            assert await repository.article(_principal("EMPLOYEE"), DOC_DRAFT) is None
            other_tenant = _principal("ANALYST", tenant_id=uuid4())
            assert await repository.articles(other_tenant, None, 21, 0) == ()
            assert await repository.article(other_tenant, DOC_EMPLOYEE) is None

            statements.clear()
            detail = await repository.article(_principal("EMPLOYEE"), DOC_EMPLOYEE)
            assert detail is not None
            sections = await repository.sections(
                TENANT_ID, detail.document_version_id, detail.published_processing_version_id
            )
            assert len(statements) == 2, "detail endpoint budget is two statements"

        assert detail.title == "Password reset FAQ"
        assert detail.document_type == "FAQ"
        assert detail.source_name == "IT Handbook"
        assert detail.version_number == 1
        assert detail.published_at is not None
        assert [section.section_title for section in sections] == ["Overview", "Steps"]
        assert sections[0].content.startswith("Passwords expire")
        assert sections[0].section_anchor == "section-1"
    finally:
        await engine.dispose()
