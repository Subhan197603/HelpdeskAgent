"""Add audited knowledge-gap disposition records.

Task 14.3 lets knowledge administrators record a bounded, deterministic
decision per analyzed query group: acknowledged, source candidate, not a
gap, or resolved. One current-state row exists per tenant and normalized
query with optimistic row versioning; the immutable history lives in
audit.audit_event, which is why UPDATE stays granted while DELETE is
revoked everywhere. Dispositions record human decisions only — they never
create sources, start acquisition, or change retrieval behavior.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032_knowledge_gap_disposition"
down_revision: str | None = "0031_retrieval_query_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb.knowledge_gap_disposition (
          disposition_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          normalized_query varchar(500) NOT NULL CHECK (normalized_query<>''),
          disposition_status varchar(20) NOT NULL CHECK (
            disposition_status IN (
              'ACKNOWLEDGED','SOURCE_CANDIDATE','NOT_A_GAP','RESOLVED'
            )
          ),
          disposition_note varchar(500),
          decided_by uuid NOT NULL REFERENCES identity.app_user(user_id),
          decided_at timestamptz NOT NULL DEFAULT now(),
          row_version integer NOT NULL DEFAULT 1 CHECK (row_version>0),
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id,normalized_query)
        );

        ALTER TABLE kb.knowledge_gap_disposition ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_knowledge_gap_disposition
          ON kb.knowledge_gap_disposition
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,INSERT,UPDATE ON kb.knowledge_gap_disposition TO helpdesk_app;
        GRANT SELECT ON kb.knowledge_gap_disposition
          TO helpdesk_reporting,helpdesk_readonly;
        REVOKE DELETE ON kb.knowledge_gap_disposition
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.knowledge_gap_disposition
          FROM helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_knowledge_gap_disposition ON kb.knowledge_gap_disposition;
        DROP TABLE kb.knowledge_gap_disposition;
        """
    )
