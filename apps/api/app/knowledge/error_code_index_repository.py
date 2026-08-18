"""Set-based, tenant-scoped listing of indexed chunk error codes."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# published_chunk_count counts the indexed chunks currently visible through
# kb.v_active_document_chunk, so publishedness is evaluated at read time and
# can never drift from rollback, suppression, or approval changes.
_LISTING_SQL = """
SELECT entry.error_code,
  count(*) AS indexed_chunk_count,
  count(active.chunk_id) AS published_chunk_count
FROM kb.chunk_error_code entry
LEFT JOIN kb.v_active_document_chunk active
  ON active.chunk_id=entry.chunk_id AND active.tenant_id=entry.tenant_id
WHERE entry.tenant_id=:tenant_id
  AND (CAST(:prefix AS varchar) IS NULL OR entry.error_code LIKE :prefix||'%')
GROUP BY entry.error_code
ORDER BY entry.error_code
LIMIT :limit OFFSET :offset
"""


class ErrorCodeIndexRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def listing(
        self, tenant_id: UUID, *, prefix: str | None, limit: int, offset: int
    ) -> list[Any]:
        rows = await self._session.execute(
            text(_LISTING_SQL),
            {"tenant_id": tenant_id, "prefix": prefix, "limit": limit, "offset": offset},
        )
        return list(rows)
