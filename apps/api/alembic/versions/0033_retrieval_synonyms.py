"""Add the governed synonym and acronym registry.

Task 15.1 gives knowledge administrators a tenant-isolated registry of
bounded term-to-expansion pairs with the deterministic lifecycle DRAFT,
APPROVED, RETIRED. Entries are retired, never deleted — the immutable
history lives in audit.audit_event, which is why UPDATE stays granted
while DELETE is revoked everywhere. This task changes no retrieval
behavior; only the separately approved Task 15.2 may read the registry
from the retrieval path.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033_retrieval_synonyms"
down_revision: str | None = "0032_knowledge_gap_disposition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb.retrieval_synonym (
          synonym_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          term varchar(100) NOT NULL CHECK (term<>''),
          expansion varchar(100) NOT NULL CHECK (expansion<>'' AND expansion<>term),
          synonym_status varchar(10) NOT NULL DEFAULT 'DRAFT' CHECK (
            synonym_status IN ('DRAFT','APPROVED','RETIRED')
          ),
          synonym_note varchar(500),
          decided_by uuid NOT NULL REFERENCES identity.app_user(user_id),
          decided_at timestamptz NOT NULL DEFAULT now(),
          row_version integer NOT NULL DEFAULT 1 CHECK (row_version>0),
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id,term,expansion)
        );
        CREATE INDEX retrieval_synonym_tenant_term_ix
          ON kb.retrieval_synonym (tenant_id,term);

        ALTER TABLE kb.retrieval_synonym ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_retrieval_synonym
          ON kb.retrieval_synonym
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,INSERT,UPDATE ON kb.retrieval_synonym TO helpdesk_app;
        GRANT SELECT ON kb.retrieval_synonym
          TO helpdesk_reporting,helpdesk_readonly;
        REVOKE DELETE ON kb.retrieval_synonym
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.retrieval_synonym
          FROM helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_retrieval_synonym ON kb.retrieval_synonym;
        DROP TABLE kb.retrieval_synonym;
        """
    )
