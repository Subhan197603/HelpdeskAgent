"""Validated project commands for adopting and operating Alembic."""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.core.settings import Settings
from apps.api.app.db.asyncio_compat import run_async
from apps.api.app.db.baseline_validation import (
    BASELINE_MARKER,
    BaselineValidationError,
    validate_physical_baseline,
)
from apps.api.app.db.migration_guard import check_migrations
from apps.api.app.db.migration_lock import MigrationLockError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_CONFIG_PATH = REPOSITORY_ROOT / "apps/api/alembic.ini"
VERSIONS_PATH = REPOSITORY_ROOT / "apps/api/alembic/versions"


def alembic_config() -> Config:
    return Config(str(ALEMBIC_CONFIG_PATH))


def validate_command(settings: Settings) -> None:
    report = run_async(validate_physical_baseline(settings))
    revision = ",".join(sorted(report.current_revisions)) or "unstamped"
    print(
        "Physical baseline validated: "
        f"{report.schema_count} schemas, {report.extension_count} extensions, "
        f"{report.table_count} representative tables, revision={revision}"
    )


def stamp_command(settings: Settings) -> None:
    report = run_async(validate_physical_baseline(settings))
    if report.current_revisions not in {frozenset(), frozenset({BASELINE_MARKER})}:
        raise BaselineValidationError(
            "Validated stamping cannot replace an existing post-baseline revision"
        )
    command.stamp(alembic_config(), BASELINE_MARKER)
    print(f"Validated physical baseline stamped at {BASELINE_MARKER}")


def upgrade_command(settings: Settings, revision: str) -> None:
    run_async(validate_physical_baseline(settings))
    command.upgrade(alembic_config(), revision)


def downgrade_command(settings: Settings, revision: str) -> None:
    run_async(validate_physical_baseline(settings))
    command.downgrade(alembic_config(), revision)


def check_command() -> None:
    findings = check_migrations(VERSIONS_PATH, REPOSITORY_ROOT)
    if findings:
        rendered = "\n".join(
            f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}"
            for finding in findings
        )
        raise CommandError("Migration validation failed:\n" + rendered)
    print("Migration validation passed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("stamp")
    subparsers.add_parser("check")
    subparsers.add_parser("current")
    subparsers.add_parser("history")
    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("revision", nargs="?", default="head")
    downgrade = subparsers.add_parser("downgrade")
    downgrade.add_argument("revision")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        if arguments.command == "check":
            check_command()
            return
        if arguments.command == "history":
            command.history(alembic_config(), verbose=True)
            return

        settings = Settings()
        if arguments.command == "validate":
            validate_command(settings)
        elif arguments.command == "stamp":
            stamp_command(settings)
        elif arguments.command == "current":
            command.current(alembic_config(), verbose=True)
        elif arguments.command == "upgrade":
            upgrade_command(settings, arguments.revision)
        elif arguments.command == "downgrade":
            downgrade_command(settings, arguments.revision)
    except (BaselineValidationError, CommandError, MigrationLockError) as exc:
        print(f"Migration command failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except SQLAlchemyError as exc:
        print(f"Migration database operation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
