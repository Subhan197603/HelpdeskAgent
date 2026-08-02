"""Background worker entry point."""

import asyncio
from contextlib import suppress

from apps.api.app.core.logging import configure_logging
from apps.api.app.core.settings import Settings
from apps.worker.worker.settings import WorkerSettings
from apps.worker.worker.sla_worker import create_worker


async def run() -> None:
    settings = WorkerSettings()
    configure_logging(Settings())
    worker, engine = create_worker(settings)
    try:
        await worker.run_forever()
    finally:
        await engine.dispose()


def main() -> None:
    with suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
