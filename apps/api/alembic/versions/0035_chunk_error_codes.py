"""Add the deterministic chunk error-code index.

Task 16.1 extracts error-code identifiers from chunk content with the same
grammar the fusion boost applies to queries and candidates, and stores them
as immutable per-chunk facts. Publishedness stays dynamic: the separately
approved Task 16.2 joins this index to kb.v_active_document_chunk at lookup
time, so rollback, suppression, and approval changes never desynchronize
the index. This task changes no retrieval behavior.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_chunk_error_codes"
down_revision: str | None = "0034_query_event_expansion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of the fusion identifier grammar as of this revision. The live
# grammar lives in apps.api.app.retrieval.fusion; migrations are immutable
# snapshots, so a later grammar change requires an explicit re-extraction
# migration rather than an edit here.
_IDENTIFIER = re.compile(
    r"(?<![A-Z0-9])(?:[A-Z]{2,12}[-_ ]\d{2,12}|[A-Z]{3,12}\d{3,12})(?![A-Z0-9])"
)

_BACKFILL_SELECT = """
SELECT chunk.chunk_id,chunk.tenant_id,document.document_title,
  chunk.heading_path,chunk.section_title,chunk.content_text
FROM kb.document_chunk chunk
JOIN kb.document document ON document.document_id=chunk.document_id
"""

_BACKFILL_INSERT = """
INSERT INTO kb.chunk_error_code (chunk_id,tenant_id,error_code)
VALUES (:chunk_id,:tenant_id,:error_code)
"""


def _error_codes(*parts: str | None) -> list[str]:
    joined = " ".join(part for part in parts if part).upper()
    return sorted(
        {
            match.group(0).replace(" ", "-").replace("_", "-")
            for match in _IDENTIFIER.finditer(joined)
        }
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb.chunk_error_code (
          chunk_id uuid NOT NULL
            REFERENCES kb.document_chunk(chunk_id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          error_code varchar(64) NOT NULL CHECK (error_code<>''),
          extracted_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (chunk_id,error_code)
        );
        CREATE INDEX chunk_error_code_tenant_code_ix
          ON kb.chunk_error_code (tenant_id,error_code,chunk_id);

        ALTER TABLE kb.chunk_error_code ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_chunk_error_code
          ON kb.chunk_error_code
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );
        CREATE TRIGGER immutable_kb_chunk_error_code
          BEFORE UPDATE OR DELETE ON kb.chunk_error_code
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        GRANT SELECT ON kb.chunk_error_code
          TO helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        GRANT INSERT ON kb.chunk_error_code TO helpdesk_worker;
        REVOKE UPDATE,DELETE ON kb.chunk_error_code
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )
    if op.get_context().as_sql:
        # Offline SQL generation cannot run the data backfill; a database
        # upgraded offline starts with an empty index that the processing
        # worker repopulates on the next reprocessing of each document.
        return
    bind = op.get_bind()
    batch: list[dict[str, object]] = []
    for row in bind.execute(sa.text(_BACKFILL_SELECT)).fetchall():
        for error_code in _error_codes(
            row.document_title, row.heading_path, row.section_title, row.content_text
        ):
            batch.append(
                {"chunk_id": row.chunk_id, "tenant_id": row.tenant_id, "error_code": error_code}
            )
        if len(batch) >= 1000:
            bind.execute(sa.text(_BACKFILL_INSERT), batch)
            batch = []
    if batch:
        bind.execute(sa.text(_BACKFILL_INSERT), batch)


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_chunk_error_code ON kb.chunk_error_code;
        DROP TRIGGER immutable_kb_chunk_error_code ON kb.chunk_error_code;
        DROP TABLE kb.chunk_error_code;
        """
    )
