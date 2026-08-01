"""Transaction-local PostgreSQL request context for future RLS policies."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.context import RequestContext

_SET_TENANT_CONTEXT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_USER_CONTEXT = text("SELECT set_config('app.user_id', :user_id, true)")


async def apply_transaction_context(
    session: AsyncSession, context: RequestContext, *, rls_enabled: bool
) -> None:
    """Apply the SET LOCAL equivalent only within an active transaction.

    PostgreSQL's parameterized ``set_config(..., true)`` is transaction-local and avoids
    interpolating caller-controlled values into SQL.
    """
    # Context is inexpensive and safe to set even when the optional baseline RLS
    # package is disabled. Alembic-owned tables may enforce tenant RLS independently.
    del rls_enabled
    if context.tenant_id is None and context.user_id is None:
        return
    if not session.in_transaction():
        raise RuntimeError("PostgreSQL request context requires an active transaction")
    if context.tenant_id is not None:
        await session.execute(_SET_TENANT_CONTEXT, {"tenant_id": str(context.tenant_id)})
    if context.user_id is not None:
        await session.execute(_SET_USER_CONTEXT, {"user_id": str(context.user_id)})
