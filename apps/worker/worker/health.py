"""Container health probe for the worker's authoritative PostgreSQL dependency."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from apps.worker.worker.settings import WorkerSettings


async def check() -> None:
    settings = WorkerSettings()
    engine = create_async_engine(settings.worker_database_url.get_secret_value())
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(check())


if __name__ == "__main__":
    main()
