"""PostgreSQL-native serialization for Alembic execution."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

MIGRATION_ADVISORY_LOCK_KEY = 6_817_315_412_136_801_249
logger = logging.getLogger(__name__)


class MigrationLockError(RuntimeError):
    """Raised when another deployment owns the migration lock."""


@asynccontextmanager
async def advisory_migration_lock(
    connection: AsyncConnection, *, timeout_seconds: float
) -> AsyncIterator[None]:
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    while time.monotonic() < deadline:
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": MIGRATION_ADVISORY_LOCK_KEY},
            )
        )
        if acquired:
            break
        await asyncio.sleep(min(0.25, timeout_seconds))
    if not acquired:
        raise MigrationLockError(
            f"Migration advisory lock was not acquired within {timeout_seconds:g} seconds"
        )
    # End SQLAlchemy's implicit transaction; the session-level advisory lock remains held.
    await connection.commit()
    try:
        yield
    finally:
        try:
            if connection.in_transaction():
                await connection.rollback()
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": MIGRATION_ADVISORY_LOCK_KEY},
            )
            await connection.commit()
        except SQLAlchemyError:
            # Closing/invalidating the PostgreSQL session also releases a session advisory lock.
            logger.error("Migration lock release required connection invalidation")
            await connection.invalidate()
