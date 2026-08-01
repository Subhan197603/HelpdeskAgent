"""Cross-platform development server entry point."""

import uvicorn

from apps.api.app.core.settings import Settings
from apps.api.app.db.asyncio_compat import run_async


def main() -> None:
    """Run Uvicorn on an event loop compatible with async Psycopg on Windows."""
    settings = Settings()
    config = uvicorn.Config(
        "apps.api.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
    run_async(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
