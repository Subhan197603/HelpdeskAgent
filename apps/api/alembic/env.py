"""Alembic environment for the existing asynchronous multi-schema database."""

import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from alembic.util import CommandError
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.app.core.settings import Settings
from apps.api.app.db.migration_lock import advisory_migration_lock
from apps.api.app.db.migration_support import (
    VERSION_TABLE,
    VERSION_TABLE_SCHEMA,
    get_migration_url,
    include_migration_name,
    include_migration_object,
    managed_metadata,
)

alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

settings = Settings()
database_url = get_migration_url(settings)
command_options = getattr(alembic_config, "cmd_opts", None)
if getattr(command_options, "autogenerate", False) and not managed_metadata.tables:
    raise CommandError(
        "Autogeneration is disabled while managed SQLAlchemy metadata is empty; "
        "create a reviewed explicit revision instead."
    )


def configure_context(connection: Connection | None = None, *, offline: bool = False) -> None:
    if offline:
        context.configure(
            url=database_url.render_as_string(hide_password=False),
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            target_metadata=managed_metadata,
            include_schemas=True,
            include_name=include_migration_name,
            include_object=include_migration_object,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
            transaction_per_migration=True,
            compare_type=True,
            compare_server_default=False,
            render_as_batch=False,
        )
    else:
        if connection is None:
            raise CommandError("Online migration configuration requires a database connection")
        context.configure(
            connection=connection,
            target_metadata=managed_metadata,
            include_schemas=True,
            include_name=include_migration_name,
            include_object=include_migration_object,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
            transaction_per_migration=True,
            compare_type=True,
            compare_server_default=False,
            render_as_batch=False,
        )


def run_migrations_offline() -> None:
    configure_context(offline=True)
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection: Connection) -> None:
    configure_context(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with (
            engine.connect() as connection,
            advisory_migration_lock(
                connection, timeout_seconds=settings.migration_lock_timeout_seconds
            ),
        ):
            await connection.run_sync(run_sync_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    if sys.platform == "win32":
        asyncio.run(run_async_migrations(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
