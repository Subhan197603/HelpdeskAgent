"""FastAPI database dependencies."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.engine import Database


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.resources.database)
    async for session in database.sessions():
        yield session
