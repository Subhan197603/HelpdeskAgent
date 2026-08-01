"""Alembic adoption tests against isolated PostgreSQL 16 databases."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from apps.api.app.core.settings import Settings
from apps.api.app.db.baseline_validation import (
    BASELINE_MARKER,
    SAMPLE_REVISION,
    BaselineValidationError,
    validate_baseline_database,
    validate_physical_baseline,
)
from apps.api.app.db.migration_lock import MIGRATION_ADVISORY_LOCK_KEY

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PROJECT = "fusion-helpdesk-alembic-test"
POSTGRES_PORT = "55441"


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = POSTGRES_PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", "compose", "--project-name", COMPOSE_PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and completed.returncode != 0:
        pytest.fail(
            f"Docker Compose failed ({completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _psql(database: str, sql: str) -> str:
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
        database,
        "-Atqc",
        sql,
    ).stdout.strip()


def _database_url(database: str) -> str:
    return f"postgresql+psycopg://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/{database}"


def _baseline_fingerprint(database: str) -> str:
    return _psql(
        database,
        "WITH inventory(item) AS ("
        "SELECT 'column:' || table_schema || '.' || table_name || '.' || column_name || ':' || "
        "data_type || ':' || is_nullable || ':' || coalesce(column_default, '') "
        "FROM information_schema.columns WHERE table_schema IN "
        "('identity','config','itsm','kb','ai','audit','integration') "
        "AND table_name <> 'alembic_version' UNION ALL "
        "SELECT 'constraint:' || n.nspname || '.' || c.relname || '.' || con.conname || ':' || "
        "pg_get_constraintdef(con.oid) FROM pg_constraint con "
        "JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname IN ('identity','config','itsm','kb','ai','audit','integration') "
        "AND c.relname <> 'alembic_version' UNION ALL "
        "SELECT 'index:' || schemaname || '.' || indexname || ':' || indexdef FROM pg_indexes "
        "WHERE schemaname IN ('identity','config','itsm','kb','ai','audit','integration') "
        "AND tablename <> 'alembic_version') "
        "SELECT md5(string_agg(item, E'\\n' ORDER BY item)) FROM inventory",
    )


def _migration_command(
    database_url: str, *arguments: str, check: bool = True, lock_timeout: str = "10"
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "MIGRATION_DATABASE_URL": database_url,
            "MIGRATION_LOCK_TIMEOUT_SECONDS": lock_timeout,
        }
    )
    completed = subprocess.run(
        ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", *arguments],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check and completed.returncode != 0:
        pytest.fail(
            f"Migration command failed ({completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


@pytest.fixture(scope="module")
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


@pytest.fixture(scope="module", autouse=True)
def postgres_stack() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


@pytest.fixture
def baseline_database() -> Iterator[tuple[str, str]]:
    database = "alembic_" + uuid4().hex[:12]
    assert database.startswith("alembic_")
    _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", database)
    try:
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
            database,
            "-f",
            "/baseline/install_all.sql",
        )
        yield database, _database_url(database)
    finally:
        _compose(
            "exec",
            "-T",
            "postgres",
            "dropdb",
            "--if-exists",
            "--force",
            "-U",
            "postgres",
            database,
            check=False,
        )


@pytest.mark.integration
@pytest.mark.anyio
async def test_baseline_validator_success_and_fail_closed_cases(
    baseline_database: tuple[str, str],
) -> None:
    _, url = baseline_database
    settings = Settings.model_validate({"app_env": "test", "migration_database_url": url})
    report = await validate_physical_baseline(settings)
    assert report.current_revisions == frozenset()

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("ALTER SCHEMA audit RENAME TO audit_missing"))
            with pytest.raises(BaselineValidationError, match="Missing required schemas"):
                await validate_baseline_database(connection)
            await transaction.rollback()

            transaction = await connection.begin()
            await connection.execute(text("ALTER TABLE itsm.ticket RENAME TO ticket_missing"))
            with pytest.raises(BaselineValidationError, match="Missing required baseline tables"):
                await validate_baseline_database(connection)
            await transaction.rollback()

            transaction = await connection.begin()
            await connection.execute(
                text("CREATE TABLE config.alembic_version (version_num varchar(32) PRIMARY KEY)")
            )
            await connection.execute(
                text("INSERT INTO config.alembic_version VALUES ('unknown_revision')")
            )
            with pytest.raises(BaselineValidationError, match="Conflicting Alembic revision"):
                await validate_baseline_database(connection)
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_validated_stamp_upgrade_downgrade_and_history(
    baseline_database: tuple[str, str],
) -> None:
    database, url = baseline_database
    fingerprint_before = _baseline_fingerprint(database)

    _migration_command(url, "validate")
    _migration_command(url, "stamp")
    _migration_command(url, "stamp")
    assert _psql(database, "SELECT version_num FROM config.alembic_version") == BASELINE_MARKER
    assert (
        _psql(
            database,
            "SELECT table_schema FROM information_schema.tables "
            "WHERE table_name = 'alembic_version'",
        )
        == "config"
    )

    current = _migration_command(url, "current")
    history = _migration_command(url, "history")
    assert BASELINE_MARKER in current.stdout
    assert BASELINE_MARKER in history.stdout
    assert SAMPLE_REVISION in history.stdout

    _migration_command(url, "upgrade", "head")
    assert _psql(database, "SELECT version_num FROM config.alembic_version") == SAMPLE_REVISION
    assert "Fusion Helpdesk physical baseline" in _psql(
        database, "SELECT obj_description('config.alembic_version'::regclass)"
    )
    restamp = _migration_command(url, "stamp", check=False)
    assert restamp.returncode != 0
    assert "cannot replace" in restamp.stderr

    _migration_command(url, "downgrade", BASELINE_MARKER)
    assert _psql(database, "SELECT obj_description('config.alembic_version'::regclass)") == ""
    _migration_command(url, "downgrade", "base")
    assert _psql(database, "SELECT count(*) FROM config.alembic_version") == "0"
    assert _baseline_fingerprint(database) == fingerprint_before

    _migration_command(url, "stamp")
    _migration_command(url, "upgrade", "head")
    assert _baseline_fingerprint(database) == fingerprint_before


@pytest.mark.integration
def test_validated_stamp_rejects_database_without_baseline() -> None:
    database = "alembic_empty_" + uuid4().hex[:10]
    assert database.startswith("alembic_empty_")
    _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", database)
    try:
        completed = _migration_command(_database_url(database), "stamp", check=False)
        assert completed.returncode != 0
        assert "Missing required schemas" in completed.stderr
        assert _psql(database, "SELECT to_regclass('config.alembic_version')") == ""
    finally:
        _compose(
            "exec",
            "-T",
            "postgres",
            "dropdb",
            "--if-exists",
            "--force",
            "-U",
            "postgres",
            database,
            check=False,
        )


@pytest.mark.integration
@pytest.mark.container
def test_compose_migrator_runs_validated_adoption(
    baseline_database: tuple[str, str],
) -> None:
    database, _ = baseline_database
    container_url = f"postgresql+psycopg://postgres:postgres@postgres:5432/{database}"

    def run(command: str) -> subprocess.CompletedProcess[str]:
        return _compose(
            "--profile",
            "tools",
            "run",
            "--rm",
            "--build",
            "-e",
            f"MIGRATION_DATABASE_URL={container_url}",
            "migrator",
            "python",
            "-m",
            "apps.api.app.db.migrations_cli",
            command,
        )

    assert "Physical baseline validated" in run("validate").stdout
    run("stamp")
    assert BASELINE_MARKER in run("current").stdout
    run("upgrade")
    assert _psql(database, "SELECT version_num FROM config.alembic_version") == SAMPLE_REVISION


@pytest.mark.integration
@pytest.mark.anyio
async def test_concurrent_migration_command_fails_on_lock_contention(
    baseline_database: tuple[str, str],
) -> None:
    _, url = baseline_database
    _migration_command(url, "stamp")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": MIGRATION_ADVISORY_LOCK_KEY},
            )
            blocked = _migration_command(url, "current", check=False, lock_timeout="1")
            assert blocked.returncode != 0
            assert "Migration advisory lock was not acquired" in blocked.stderr
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": MIGRATION_ADVISORY_LOCK_KEY},
            )
    finally:
        await engine.dispose()
