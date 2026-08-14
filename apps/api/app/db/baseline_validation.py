"""Fail-closed validation for adopting the approved physical baseline."""

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.app.core.settings import Settings
from apps.api.app.db.migration_support import get_migration_url

BASELINE_MARKER = "0000_physical_baseline"
SAMPLE_REVISION = "0025_analyst_canned_responses"
EXPECTED_SCHEMAS = frozenset({"identity", "config", "itsm", "kb", "ai", "audit", "integration"})
EXPECTED_EXTENSIONS = frozenset({"pgcrypto", "pg_trgm", "unaccent", "vector"})
EXPECTED_TABLES = frozenset(
    {
        "identity.tenant",
        "config.request_type_version",
        "config.application_environment",
        "config.priority_matrix",
        "config.retention_policy",
        "itsm.ticket",
        "itsm.ticket_attachment",
        "kb.document",
        "ai.feature_policy",
        "ai.usage_ledger",
        "audit.audit_event",
        "audit.legal_hold",
        "integration.idempotency_record",
        "integration.email_message",
    }
)
EXPECTED_RELEASES = frozenset({"FUSION_APPLICATIONS/26C", "FUSION_DATA_INTELLIGENCE/26.R2"})


class BaselineValidationError(RuntimeError):
    """Raised when a database cannot safely adopt the baseline marker."""


@dataclass(frozen=True, slots=True)
class BaselineValidationReport:
    schema_count: int
    extension_count: int
    table_count: int
    current_revisions: frozenset[str]


def default_baseline_path() -> Path:
    return Path(__file__).resolve().parents[4] / "database/baseline/fusion_helpdesk_postgres"


def known_revision_ids() -> frozenset[str]:
    versions = Path(__file__).resolve().parents[2] / "alembic/versions"
    revisions: set[str] = set()
    for path in versions.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "revision"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                revisions.add(node.value.value)
    if BASELINE_MARKER not in revisions:
        raise BaselineValidationError("Physical-baseline marker revision is missing")
    return frozenset(revisions)


def validate_baseline_package(package_path: Path | None = None) -> int:
    package = (package_path or default_baseline_path()).resolve()
    checksum_file = package / "SHA256SUMS.txt"
    if not checksum_file.is_file():
        raise BaselineValidationError("Physical-baseline checksum manifest is missing")
    checked = 0
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        try:
            expected_hash, relative_name = line.split("  ./", maxsplit=1)
        except ValueError as exc:
            raise BaselineValidationError("Invalid physical-baseline checksum manifest") from exc
        candidate = (package / relative_name).resolve()
        if package not in candidate.parents or not candidate.is_file():
            raise BaselineValidationError(f"Invalid baseline manifest entry: {relative_name}")
        actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise BaselineValidationError(f"Baseline checksum mismatch: {relative_name}")
        checked += 1
    if checked == 0:
        raise BaselineValidationError("Physical-baseline checksum manifest is empty")
    return checked


async def _string_set(connection: AsyncConnection, statement: str) -> frozenset[str]:
    result = await connection.execute(text(statement))
    return frozenset(str(row[0]) for row in result)


async def validate_baseline_database(connection: AsyncConnection) -> BaselineValidationReport:
    schemas = await _string_set(
        connection,
        "SELECT schema_name FROM information_schema.schemata",
    )
    missing_schemas = EXPECTED_SCHEMAS - schemas
    if missing_schemas:
        raise BaselineValidationError(
            "Missing required schemas: " + ", ".join(sorted(missing_schemas))
        )

    extensions = await _string_set(connection, "SELECT extname FROM pg_extension")
    missing_extensions = EXPECTED_EXTENSIONS - extensions
    if missing_extensions:
        raise BaselineValidationError(
            "Missing required extensions: " + ", ".join(sorted(missing_extensions))
        )

    tables = await _string_set(
        connection,
        "SELECT table_schema || '.' || table_name FROM information_schema.tables",
    )
    missing_tables = EXPECTED_TABLES - tables
    if missing_tables:
        raise BaselineValidationError(
            "Missing required baseline tables: " + ", ".join(sorted(missing_tables))
        )

    config_releases = await _string_set(
        connection,
        "SELECT release_family || '/' || release_code FROM config.product_release",
    )
    knowledge_releases = await _string_set(
        connection,
        "SELECT release_family || '/' || release_code FROM kb.release",
    )
    if not config_releases >= EXPECTED_RELEASES or not knowledge_releases >= EXPECTED_RELEASES:
        raise BaselineValidationError(
            "Expected Fusion Applications and Fusion Data Intelligence releases are missing"
        )

    version_table = await connection.scalar(text("SELECT to_regclass('config.alembic_version')"))
    revisions: frozenset[str] = frozenset()
    if version_table is not None:
        revisions = await _string_set(connection, "SELECT version_num FROM config.alembic_version")
        unknown = revisions - known_revision_ids()
        if unknown or len(revisions) > 1:
            rendered = ", ".join(sorted(revisions)) or "<empty>"
            raise BaselineValidationError(f"Conflicting Alembic revision state: {rendered}")

    return BaselineValidationReport(
        schema_count=len(EXPECTED_SCHEMAS),
        extension_count=len(EXPECTED_EXTENSIONS),
        table_count=len(EXPECTED_TABLES),
        current_revisions=revisions,
    )


async def validate_physical_baseline(settings: Settings) -> BaselineValidationReport:
    validate_baseline_package()
    engine = create_async_engine(get_migration_url(settings), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await validate_baseline_database(connection)
    finally:
        await engine.dispose()
