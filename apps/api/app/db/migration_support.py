"""Shared Alembic configuration and partial-metadata safety boundaries."""

from collections.abc import MutableMapping
from typing import Any, Literal

from alembic.util import CommandError
from sqlalchemy import MetaData
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from apps.api.app.core.settings import Settings

VERSION_TABLE_SCHEMA = "config"
VERSION_TABLE = "alembic_version"
APPROVED_SCHEMAS = frozenset({"identity", "config", "itsm", "kb", "ai", "audit", "integration"})

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
managed_metadata = MetaData(naming_convention=NAMING_CONVENTION)

type MigrationObjectType = Literal[
    "schema", "table", "column", "index", "unique_constraint", "foreign_key_constraint"
]
type ParentNameKey = Literal["schema_name", "table_name", "schema_qualified_table_name"]


def get_migration_url(settings: Settings) -> URL:
    configured = settings.migration_database_url
    if settings.is_production and configured is None:
        raise CommandError("MIGRATION_DATABASE_URL is required for production migrations")
    secret = configured or settings.database_url
    try:
        url = make_url(secret.get_secret_value())
    except ArgumentError:
        raise CommandError("Migration database URL is invalid") from None
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise CommandError("Alembic requires a PostgreSQL psycopg database URL")
    return url


def include_migration_name(
    name: str | None,
    object_type: MigrationObjectType,
    parent_names: MutableMapping[ParentNameKey, str | None],
) -> bool:
    if object_type == "schema":
        return name in APPROVED_SCHEMAS
    schema_name = parent_names.get("schema_name")
    if schema_name is not None and schema_name not in APPROVED_SCHEMAS:
        return False
    if object_type == "table":
        if name == VERSION_TABLE:
            return False
        table_key = f"{schema_name}.{name}" if schema_name else str(name)
        return table_key in managed_metadata.tables
    return True


def include_migration_object(
    obj: Any,
    name: str | None,
    object_type: str,
    reflected: bool,
    compare_to: Any | None,
) -> bool:
    schema = getattr(obj, "schema", None)
    if schema is not None and schema not in APPROVED_SCHEMAS:
        return False
    if object_type == "table" and name == VERSION_TABLE and schema == VERSION_TABLE_SCHEMA:
        return False
    # Baseline tables without matching application metadata are externally managed, not removed.
    return not (reflected and compare_to is None)
