"""Explicit async transaction boundary for application services."""

from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.core.context import RequestContext
from apps.api.app.db.transaction_context import apply_transaction_context


class AsyncUnitOfWork(Protocol):
    session: AsyncSession

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        context: RequestContext,
        *,
        rls_enabled: bool,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._rls_enabled = rls_enabled
        self._completed = False
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered")
        return self._session

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of work cannot be re-entered")
        self._session = self._session_factory()
        await self.session.begin()
        await apply_transaction_context(self.session, self._context, rls_enabled=self._rls_enabled)
        return self

    async def commit(self) -> None:
        await self.session.commit()
        self._completed = True

    async def rollback(self) -> None:
        await self.session.rollback()
        self._completed = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if not self._completed and self.session.in_transaction():
                await self.session.rollback()
        finally:
            await self.session.close()
