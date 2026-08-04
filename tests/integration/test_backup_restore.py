"""Task 10.3 backup, restore, and disaster-recovery validation against PostgreSQL."""

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-backup-test"
PORT = "55462"
DATABASE = "backup_model"
BACKUP_PATH = "/tmp/backup_model.dump"
RTO_BUDGET_SECONDS = 180.0
SEEDED_TICKETS = 100


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


def _psql(sql: str, *, database: str = DATABASE, check: bool = True) -> str:
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
        check=check,
    ).stdout.strip()


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


def _run_script(script: str, extra_env: dict[str, str]) -> None:
    _compose("cp", str(ROOT / "infrastructure/backup" / script), f"postgres:/tmp/{script}")
    assignments = " ".join(f"{key}={value}" for key, value in extra_env.items())
    _compose("exec", "-T", "postgres", "bash", "-c", f"{assignments} bash /tmp/{script}")


def _data_fingerprint(database: str = DATABASE) -> tuple[int, str]:
    count = int(_psql("SELECT count(*) FROM itsm.ticket", database=database))
    digest = _psql(
        "SELECT coalesce(md5(string_agg(ticket_key || '|' || summary, ',' "
        "ORDER BY ticket_key)), 'empty') FROM itsm.ticket",
        database=database,
    )
    return count, digest


@pytest.fixture(scope="module", autouse=True)
def backup_database() -> Iterator[None]:
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
        for file in ("/development/identity_personas.sql", "/development/catalogue.sql"):
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
            f"""
            INSERT INTO itsm.ticket(
              tenant_id,project_id,request_type_id,request_type_version_id,work_type_id,
              workflow_version_id,status_id,summary,reporter_user_id,priority_code,
              channel_code,created_by,updated_by)
            SELECT '20000000-0000-0000-0000-000000000001',request_type.project_id,
              request_type.request_type_id,request_version.request_type_version_id,
              request_type.work_type_id,'32100000-0000-0000-0000-000000000001',
              '32200000-0000-0000-0000-000000000002',
              'Recovery drill ticket ' || series,
              '22000000-0000-0000-0000-000000000005','P3','PORTAL',
              '22000000-0000-0000-0000-000000000005','22000000-0000-0000-0000-000000000005'
            FROM generate_series(1,{SEEDED_TICKETS}) series
            JOIN config.request_type request_type
              ON request_type.request_type_id='33000000-0000-0000-0000-000000000001'
            JOIN config.request_type_version request_version
              ON request_version.request_type_id=request_type.request_type_id
             AND request_version.version_status='PUBLISHED';
            """
        )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


@pytest.mark.integration
def test_pitr_prerequisites_are_enabled() -> None:
    assert _psql("SHOW wal_level") in {"replica", "logical"}
    assert _psql("SHOW full_page_writes") == "on"


@pytest.mark.integration
def test_backup_restore_preserves_data_bounds_rpo_and_meets_rto() -> None:
    expected_count, expected_digest = _data_fingerprint()
    assert expected_count >= SEEDED_TICKETS

    _run_script(
        "backup_database.sh",
        {"BACKUP_DATABASE": DATABASE, "BACKUP_PATH": BACKUP_PATH},
    )
    # Writes made after the backup point must not survive a restore of that
    # backup: this bounds the recovery point to the last completed backup.
    _psql("CREATE TABLE public.rpo_marker(created_after_backup boolean NOT NULL)")
    _psql("INSERT INTO public.rpo_marker VALUES (true)")

    started = time.perf_counter()
    _run_script(
        "restore_database.sh",
        {"RESTORE_DATABASE": DATABASE, "BACKUP_PATH": BACKUP_PATH},
    )
    restore_seconds = time.perf_counter() - started
    assert restore_seconds < RTO_BUDGET_SECONDS, f"restore took {restore_seconds:.1f}s"

    restored_count, restored_digest = _data_fingerprint()
    assert (restored_count, restored_digest) == (expected_count, expected_digest)
    marker = _psql("SELECT to_regclass('public.rpo_marker')")
    assert marker in {"", "NULL"}, "post-backup write survived restore"


@pytest.mark.integration
def test_restored_database_remains_at_migration_head_and_enforces_immutability() -> None:
    _migrate("check")
    failure = _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-U",
        "postgres",
        "-d",
        DATABASE,
        "-Atqc",
        "DELETE FROM itsm.ticket_event",
        check=False,
    )
    assert failure.returncode != 0, "append-only enforcement lost after restore"
