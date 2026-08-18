"""Alembic configuration, marker, and migration-policy tests."""

import ast
import os
import subprocess
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table

from apps.api.app.db.baseline_validation import BASELINE_MARKER, validate_baseline_package
from apps.api.app.db.migration_guard import check_migrations, inspect_revision
from apps.api.app.db.migration_support import (
    VERSION_TABLE_SCHEMA,
    ParentNameKey,
    get_migration_url,
    include_migration_name,
    include_migration_object,
    managed_metadata,
)

from .conftest import make_test_settings

ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG = ROOT / "apps/api/alembic.ini"
VERSIONS = ROOT / "apps/api/alembic/versions"


def _function_calls(path: Path, function_name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [child for child in ast.walk(node) if isinstance(child, ast.Call)]
    raise AssertionError(f"Missing function: {function_name}")


def test_alembic_configuration_and_linear_history_load() -> None:
    config = Config(str(ALEMBIC_CONFIG))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    assert [revision.revision for revision in revisions] == [
        "0034_query_event_expansion",
        "0033_retrieval_synonyms",
        "0032_knowledge_gap_disposition",
        "0031_retrieval_query_events",
        "0030_corpus_publication",
        "0029_corpus_validation",
        "0028_content_change_detection",
        "0027_knowledge_source_lifecycle",
        "0026_analyst_ticket_watchlist",
        "0025_analyst_canned_responses",
        "0024_analyst_saved_filters",
        "0023_knowledge_admin_index",
        "0022_admin_config_privileges",
        "0021_admin_access_privileges",
        "0020_reporting_views",
        "0019_analyst_feedback",
        "0018_agent_escalation",
        "0017_employee_agent",
        "0016_retrieval_fusion",
        "0015_hybrid_retrieval",
        "0014_knowledge_processing",
        "0013_document_acquisition",
        "0012_knowledge_source_governance",
        "0011_notification_delivery",
        "0010_approval_engine",
        "0009_business_calendar_sla",
        "0008_attachment_lifecycle",
        "0007_queue_performance_indexes",
        "0006_ticket_draft_submission",
        "0005_catalogue_form_immutability",
        "0004_oidc_external_identity",
        "0003_rls_runtime_privileges",
        "0002_identity_role_activation",
        "0001_migration_metadata",
        BASELINE_MARKER,
    ]
    assert script.get_heads() == ["0034_query_event_expansion"]
    assert config.get_main_option("sqlalchemy.url") is None
    assert VERSION_TABLE_SCHEMA == "config"


def test_marker_upgrade_and_downgrade_have_no_operations() -> None:
    marker = VERSIONS / "0000_physical_baseline.py"
    assert _function_calls(marker, "upgrade") == []
    assert _function_calls(marker, "downgrade") == []
    source = marker.read_text(encoding="utf-8").lower()
    assert "install_all.sql" not in source
    assert "drop schema" not in source


def test_offline_sql_contains_only_alembic_owned_changes_and_no_secret() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "MIGRATION_DATABASE_URL": (
                "postgresql+psycopg://migrator:offline-secret@localhost/helpdesk"
            ),
        }
    )
    completed = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_CONFIG), "upgrade", "head", "--sql"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "config.alembic_version" in output
    assert "COMMENT ON TABLE config.alembic_version" in output
    assert "CREATE TABLE itsm.ticket (" not in output
    assert "CREATE TABLE itsm.ticket_draft" in output
    baseline_schemas = ("identity", "config", "itsm", "kb", "ai", "audit", "integration", "util")
    for schema in baseline_schemas:
        assert f"CREATE SCHEMA {schema}" not in output
    assert "CREATE SCHEMA reporting" in output
    assert "offline-secret" not in output


def test_migration_url_uses_typed_settings_and_is_redacted() -> None:
    settings = make_test_settings(
        migration_database_url="postgresql://migrator:private-value@db/helpdesk"
    )
    url = get_migration_url(settings)
    assert url.drivername == "postgresql+psycopg"
    assert "private-value" not in repr(url)


def test_baseline_package_checksums_are_valid() -> None:
    assert validate_baseline_package() > 0


def test_current_migrations_pass_policy_guard() -> None:
    assert check_migrations(VERSIONS, ROOT) == []


def test_destructive_guard_rejects_unapproved_operation(tmp_path: Path) -> None:
    revision = tmp_path / "0002_test_drop.py"
    revision.write_text(
        "revision: str = '0002_test_drop'\n"
        "down_revision: str | None = '0001_migration_metadata'\n"
        "def upgrade():\n"
        "    op.drop_table('ticket', schema='itsm')\n",
        encoding="utf-8",
    )
    _, findings = inspect_revision(revision, ROOT)
    assert any(finding.rule == "destructive-operation" for finding in findings)


def test_destructive_downgrade_does_not_require_upgrade_approval(tmp_path: Path) -> None:
    revision = tmp_path / "0002_test_add.py"
    revision.write_text(
        "revision: str = '0002_test_add'\n"
        "down_revision: str | None = '0001_migration_metadata'\n"
        "def upgrade():\n"
        "    op.add_column('app_user', column, schema='identity')\n"
        "def downgrade():\n"
        "    op.drop_column('app_user', 'value', schema='identity')\n",
        encoding="utf-8",
    )
    _, findings = inspect_revision(revision, ROOT)
    assert not any(finding.rule == "destructive-operation" for finding in findings)


def test_destructive_override_requires_matching_adr(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    decisions = repository / "docs/decisions"
    decisions.mkdir(parents=True)
    (decisions / "ADR-9999-reviewed-drop.md").write_text(
        "Approved migration: 0002_test_drop\n", encoding="utf-8"
    )
    revision = tmp_path / "0002_test_drop.py"
    revision.write_text(
        "# DESTRUCTIVE_MIGRATION_APPROVED: ADR-9999\n"
        "revision: str = '0002_test_drop'\n"
        "down_revision: str | None = '0001_migration_metadata'\n"
        "def upgrade():\n"
        "    op.drop_table('ticket', schema='itsm')\n",
        encoding="utf-8",
    )
    _, findings = inspect_revision(revision, repository)
    assert not any(finding.rule == "destructive-operation" for finding in findings)


def test_partial_metadata_never_treats_unmapped_baseline_table_as_removed() -> None:
    reflected_metadata = MetaData()
    reflected_table = Table("ticket", reflected_metadata, schema="itsm")
    parent_names: dict[ParentNameKey, str | None] = {
        "schema_name": "itsm",
        "table_name": "ticket",
        "schema_qualified_table_name": "itsm.ticket",
    }
    assert managed_metadata.tables == {}
    assert not include_migration_name("ticket", "table", parent_names)
    assert not include_migration_object(
        reflected_table, "ticket", "table", reflected=True, compare_to=None
    )
