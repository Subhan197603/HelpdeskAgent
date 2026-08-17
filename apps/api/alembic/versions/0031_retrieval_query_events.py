"""Add append-only tenant-isolated retrieval query events.

Task 14.1 captures one observational event per successful retrieval
invocation: the bounded normalized query text, the requesting surface, the
result count, the zero-result flag, the top fused score, and the tenant's
active corpus version at query time. Events never change retrieval behavior;
they are raw evidence for the later Task 14.2 zero-result and low-confidence
analytics. Rows are immutable except for the bounded, tenant-scoped retention
sweep, which is why DELETE stays granted to the application role while UPDATE
is revoked and trigger-rejected.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031_retrieval_query_events"
down_revision: str | None = "0030_corpus_publication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb.retrieval_query_event (
          event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          surface varchar(30) NOT NULL CHECK (
            surface IN ('EVIDENCE_SEARCH','EMPLOYEE_AGENT','ANALYST_COPILOT')
          ),
          normalized_query varchar(500) NOT NULL CHECK (normalized_query<>''),
          result_count integer NOT NULL CHECK (result_count>=0),
          zero_result_flag boolean NOT NULL,
          top_score double precision CHECK (
            (zero_result_flag AND top_score IS NULL)
            OR (NOT zero_result_flag AND top_score IS NOT NULL)
          ),
          corpus_version_id uuid REFERENCES kb.corpus_version(corpus_version_id),
          captured_at timestamptz NOT NULL DEFAULT now(),
          CHECK (zero_result_flag=(result_count=0))
        );
        CREATE INDEX retrieval_query_event_tenant_time_ix
          ON kb.retrieval_query_event (tenant_id,captured_at);
        CREATE INDEX retrieval_query_event_group_ix
          ON kb.retrieval_query_event (tenant_id,normalized_query,captured_at);
        CREATE TRIGGER immutable_kb_retrieval_query_event
          BEFORE UPDATE ON kb.retrieval_query_event
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        ALTER TABLE kb.retrieval_query_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_retrieval_query_event ON kb.retrieval_query_event
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        -- DELETE is granted to the application role solely for the bounded
        -- tenant-scoped retention sweep; UPDATE is both revoked and rejected
        -- by trigger so captured evidence can expire but never change.
        GRANT SELECT,INSERT,DELETE ON kb.retrieval_query_event TO helpdesk_app;
        GRANT SELECT ON kb.retrieval_query_event
          TO helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.retrieval_query_event
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE DELETE ON kb.retrieval_query_event
          FROM helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_retrieval_query_event ON kb.retrieval_query_event;
        DROP TRIGGER immutable_kb_retrieval_query_event
          ON kb.retrieval_query_event;
        DROP TABLE kb.retrieval_query_event;
        """
    )
