"""Add persisted corpus validation runs, findings, and suppression flags.

Corpus validation produces a pre-publication report over the tenant-visible
corpus: structural defects, empty chunks, duplicate documents, and
near-duplicate chunk suppression flags. Findings are append-only evidence.
The suppression flag on kb.document_chunk is advisory in this task: it never
changes retrieval eligibility, which only a later approved publication may
apply, and the canonical member of every duplicate group stays unflagged so
the last visible copy of content is never removed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_corpus_validation"
down_revision: str | None = "0028_content_change_detection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb.corpus_validation_run (
          run_id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          run_status varchar(20) NOT NULL DEFAULT 'COMPLETED' CHECK (
            run_status IN ('COMPLETED','FAILED')
          ),
          requested_by uuid NOT NULL REFERENCES identity.app_user(user_id),
          similarity_threshold numeric(4,3) NOT NULL CHECK (
            similarity_threshold>0 AND similarity_threshold<=1
          ),
          document_count integer NOT NULL DEFAULT 0 CHECK (document_count>=0),
          chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count>=0),
          structural_defect_count integer NOT NULL DEFAULT 0 CHECK (
            structural_defect_count>=0
          ),
          empty_chunk_count integer NOT NULL DEFAULT 0 CHECK (empty_chunk_count>=0),
          duplicate_document_count integer NOT NULL DEFAULT 0 CHECK (
            duplicate_document_count>=0
          ),
          near_duplicate_chunk_count integer NOT NULL DEFAULT 0 CHECK (
            near_duplicate_chunk_count>=0
          ),
          truncated_flag boolean NOT NULL DEFAULT false,
          correlation_id uuid,
          request_id varchar(200),
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          row_version integer NOT NULL DEFAULT 1 CHECK (row_version>0)
        );
        CREATE INDEX corpus_validation_run_tenant_ix
          ON kb.corpus_validation_run (tenant_id,created_at DESC,run_id DESC);

        CREATE TABLE kb.corpus_validation_finding (
          finding_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          run_id uuid NOT NULL REFERENCES kb.corpus_validation_run(run_id)
            ON DELETE CASCADE,
          finding_type varchar(30) NOT NULL CHECK (
            finding_type IN (
              'STRUCTURAL_DEFECT','EMPTY_CHUNK','DUPLICATE_DOCUMENT',
              'NEAR_DUPLICATE_CHUNK'
            )
          ),
          document_id uuid NOT NULL REFERENCES kb.document(document_id)
            ON DELETE CASCADE,
          document_version_id uuid REFERENCES kb.document_version(document_version_id)
            ON DELETE CASCADE,
          chunk_id uuid,
          counterpart_document_id uuid REFERENCES kb.document(document_id)
            ON DELETE CASCADE,
          counterpart_chunk_id uuid,
          duplicate_group_key varchar(64),
          similarity_score numeric(5,4) CHECK (
            similarity_score IS NULL OR (similarity_score>=0 AND similarity_score<=1)
          ),
          suppression_flagged boolean NOT NULL DEFAULT false,
          evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX corpus_validation_finding_run_ix
          ON kb.corpus_validation_finding (tenant_id,run_id,finding_type,finding_id);
        CREATE INDEX corpus_validation_finding_group_ix
          ON kb.corpus_validation_finding (run_id,duplicate_group_key);
        CREATE TRIGGER immutable_kb_corpus_validation_finding
          BEFORE UPDATE OR DELETE ON kb.corpus_validation_finding
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        ALTER TABLE kb.document_chunk
          ADD COLUMN near_duplicate_suppressed_flag boolean NOT NULL DEFAULT false;

        ALTER TABLE kb.corpus_validation_run ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.corpus_validation_finding ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_corpus_validation_run ON kb.corpus_validation_run
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_corpus_validation_finding ON kb.corpus_validation_finding
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,INSERT,UPDATE ON kb.corpus_validation_run TO helpdesk_app;
        GRANT SELECT,INSERT ON kb.corpus_validation_finding TO helpdesk_app;
        GRANT SELECT ON kb.corpus_validation_run,kb.corpus_validation_finding
          TO helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE DELETE ON kb.corpus_validation_run,kb.corpus_validation_finding
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.corpus_validation_finding
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        GRANT UPDATE (near_duplicate_suppressed_flag) ON kb.document_chunk
          TO helpdesk_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE UPDATE (near_duplicate_suppressed_flag) ON kb.document_chunk
          FROM helpdesk_app;
        ALTER TABLE kb.document_chunk DROP COLUMN near_duplicate_suppressed_flag;
        DROP POLICY tenant_corpus_validation_finding ON kb.corpus_validation_finding;
        DROP POLICY tenant_corpus_validation_run ON kb.corpus_validation_run;
        DROP TRIGGER immutable_kb_corpus_validation_finding
          ON kb.corpus_validation_finding;
        DROP TABLE kb.corpus_validation_finding;
        DROP TABLE kb.corpus_validation_run;
        """
    )
