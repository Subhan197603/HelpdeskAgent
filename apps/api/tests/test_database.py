"""Unit-of-work and PostgreSQL transaction-context unit tests."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.core.context import RequestContext
from apps.api.app.db.engine import Database
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork


def context() -> RequestContext:
    return RequestContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        external_subject=None,
        roles=frozenset(),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id=str(uuid4()),
        request_id=str(uuid4()),
    )


@pytest.mark.anyio
async def test_transaction_context_is_parameterized_and_transaction_local() -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.execute = AsyncMock()
    await apply_transaction_context(session, context(), rls_enabled=True)
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert len(statements) == 2
    assert all("set_config" in statement and "true" in statement for statement in statements)
    assert all("SET app." not in statement for statement in statements)
    assert all(":tenant_id" in statements[0] or ":user_id" in statements[1] for _ in [0])


@pytest.mark.anyio
async def test_transaction_context_requires_active_transaction() -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    with pytest.raises(RuntimeError, match="active transaction"):
        await apply_transaction_context(session, context(), rls_enabled=True)


def unit_of_work() -> tuple[SqlAlchemyUnitOfWork, MagicMock]:
    session = MagicMock(spec=AsyncSession)
    session.begin = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.in_transaction.return_value = True
    factory = MagicMock(return_value=session)
    uow = SqlAlchemyUnitOfWork(
        cast(async_sessionmaker[AsyncSession], factory), context(), rls_enabled=False
    )
    return uow, session


@pytest.mark.anyio
async def test_unit_of_work_commit_and_session_cleanup() -> None:
    uow, session = unit_of_work()
    async with uow:
        await uow.commit()
    session.begin.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()


@pytest.mark.anyio
async def test_unit_of_work_rolls_back_uncommitted_work() -> None:
    uow, session = unit_of_work()
    async with uow:
        pass
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.anyio
async def test_database_session_factory_closes_session_context() -> None:
    session = MagicMock(spec=AsyncSession)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=session)
    database = object.__new__(Database)
    database.session_factory = cast(async_sessionmaker[AsyncSession], factory)

    iterator = database.sessions()
    assert await anext(iterator) is session
    await iterator.aclose()
    session.__aexit__.assert_awaited_once()
