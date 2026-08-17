"""Add governed corpus publication versions, suppression snapshots, and rollback.

Corpus publication applies a validated corpus state to retrieval as an
explicit, human-approved admin action. Each publication creates an immutable
kb.corpus_version row that snapshots the advisory near-duplicate suppression
flags into kb.corpus_version_suppressed_chunk; retrieval excludes exactly the
chunks suppressed by the tenant's single active version. Rollback reactivates
the prior immutable version through the same atomic active-flag switch and is
recorded, like publication, in the append-only kb.corpus_publication_event
table. With no active version, retrieval eligibility is unchanged, preserving
the Task 13.3 advisory semantics.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030_corpus_publication"
down_revision: str | None = "0029_corpus_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb.corpus_version (
          corpus_version_id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          version_number integer NOT NULL CHECK (version_number>0),
          validation_run_id uuid NOT NULL REFERENCES kb.corpus_validation_run(run_id),
          published_by uuid NOT NULL REFERENCES identity.app_user(user_id),
          published_at timestamptz NOT NULL DEFAULT now(),
          document_count integer NOT NULL CHECK (document_count>=0),
          chunk_count integer NOT NULL CHECK (chunk_count>=0),
          suppressed_chunk_count integer NOT NULL CHECK (suppressed_chunk_count>=0),
          active_flag boolean NOT NULL DEFAULT false,
          row_version integer NOT NULL DEFAULT 1 CHECK (row_version>0),
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id,version_number)
        );
        CREATE UNIQUE INDEX corpus_version_single_active_ux
          ON kb.corpus_version (tenant_id) WHERE active_flag;
        CREATE INDEX corpus_version_history_ix
          ON kb.corpus_version (tenant_id,version_number DESC);

        CREATE TABLE kb.corpus_version_suppressed_chunk (
          corpus_version_id uuid NOT NULL REFERENCES kb.corpus_version(corpus_version_id)
            ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          chunk_id uuid NOT NULL,
          PRIMARY KEY (corpus_version_id,chunk_id)
        );
        CREATE INDEX corpus_version_suppressed_chunk_ix
          ON kb.corpus_version_suppressed_chunk (chunk_id,corpus_version_id);
        CREATE TRIGGER immutable_kb_corpus_version_suppressed_chunk
          BEFORE UPDATE OR DELETE ON kb.corpus_version_suppressed_chunk
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        CREATE TABLE kb.corpus_publication_event (
          publication_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          action_code varchar(20) NOT NULL CHECK (
            action_code IN ('PUBLISHED','ROLLED_BACK')
          ),
          corpus_version_id uuid NOT NULL REFERENCES kb.corpus_version(corpus_version_id),
          previous_corpus_version_id uuid REFERENCES kb.corpus_version(corpus_version_id),
          actor_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
          evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          correlation_id uuid,
          request_id varchar(200),
          deduplication_key varchar(250) NOT NULL,
          occurred_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id,deduplication_key)
        );
        CREATE INDEX corpus_publication_event_history_ix
          ON kb.corpus_publication_event (tenant_id,occurred_at DESC,publication_event_id DESC);
        CREATE TRIGGER immutable_kb_corpus_publication_event
          BEFORE UPDATE OR DELETE ON kb.corpus_publication_event
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        ALTER TABLE kb.corpus_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.corpus_version_suppressed_chunk ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.corpus_publication_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_corpus_version ON kb.corpus_version
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_corpus_version_suppressed_chunk
          ON kb.corpus_version_suppressed_chunk
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_corpus_publication_event ON kb.corpus_publication_event
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,INSERT,UPDATE ON kb.corpus_version TO helpdesk_app;
        GRANT SELECT,INSERT ON kb.corpus_version_suppressed_chunk,
          kb.corpus_publication_event TO helpdesk_app;
        GRANT SELECT ON kb.corpus_version,kb.corpus_version_suppressed_chunk,
          kb.corpus_publication_event
          TO helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE DELETE ON kb.corpus_version,kb.corpus_version_suppressed_chunk,
          kb.corpus_publication_event
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.corpus_version_suppressed_chunk,kb.corpus_publication_event
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;

        -- kb.v_active_document_chunk executes with the privileges of its
        -- baseline owner (helpdesk_owner). Align the new tables with the
        -- baseline ownership convention so the view's suppression subquery is
        -- deterministic even when optional RLS is enabled: the owner bypasses
        -- row security exactly like every baseline kb table, while runtime
        -- roles remain policy-scoped.
        ALTER TABLE kb.corpus_version OWNER TO helpdesk_owner;
        ALTER TABLE kb.corpus_version_suppressed_chunk OWNER TO helpdesk_owner;
        ALTER TABLE kb.corpus_publication_event OWNER TO helpdesk_owner;

        CREATE OR REPLACE VIEW kb.v_active_document_chunk AS
        SELECT c.chunk_id,c.document_version_id,d.document_id,d.tenant_id,
          d.document_title,d.document_type,d.audience_code,d.security_classification,
          d.canonical_url,d.release_id,d.product_node_id,c.heading_path,c.chapter_title,
          c.section_title,c.section_anchor,c.page_number,c.content_text,c.search_vector,
          r.release_family,r.release_code,pn.product_code,pn.product_name,
          s.source_type,s.source_name
        FROM kb.document_chunk c
        JOIN kb.document_version dv ON dv.document_version_id=c.document_version_id
          AND dv.current_version_flag
          AND dv.validation_status IN ('PASSED','WARNING')
          AND c.processing_version_id=dv.published_processing_version_id
        JOIN kb.document d ON d.document_id=dv.document_id AND d.active_flag
          AND d.approval_status='APPROVED'
          AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
          AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
        JOIN kb.source s ON s.source_id=d.source_id AND s.active_flag
        LEFT JOIN kb.release r ON r.release_id=d.release_id
        LEFT JOIN kb.product_node pn ON pn.product_node_id=d.product_node_id
        WHERE NOT EXISTS (
          SELECT 1 FROM kb.corpus_version_suppressed_chunk suppressed
          JOIN kb.corpus_version active_version
            ON active_version.corpus_version_id=suppressed.corpus_version_id
            AND active_version.active_flag
          WHERE suppressed.chunk_id=c.chunk_id
            AND active_version.tenant_id=c.tenant_id
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW kb.v_active_document_chunk AS
        SELECT c.chunk_id,c.document_version_id,d.document_id,d.tenant_id,
          d.document_title,d.document_type,d.audience_code,d.security_classification,
          d.canonical_url,d.release_id,d.product_node_id,c.heading_path,c.chapter_title,
          c.section_title,c.section_anchor,c.page_number,c.content_text,c.search_vector,
          r.release_family,r.release_code,pn.product_code,pn.product_name,
          s.source_type,s.source_name
        FROM kb.document_chunk c
        JOIN kb.document_version dv ON dv.document_version_id=c.document_version_id
          AND dv.current_version_flag
          AND dv.validation_status IN ('PASSED','WARNING')
          AND c.processing_version_id=dv.published_processing_version_id
        JOIN kb.document d ON d.document_id=dv.document_id AND d.active_flag
          AND d.approval_status='APPROVED'
          AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
          AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
        JOIN kb.source s ON s.source_id=d.source_id AND s.active_flag
        LEFT JOIN kb.release r ON r.release_id=d.release_id
        LEFT JOIN kb.product_node pn ON pn.product_node_id=d.product_node_id;

        DROP POLICY tenant_corpus_publication_event ON kb.corpus_publication_event;
        DROP POLICY tenant_corpus_version_suppressed_chunk
          ON kb.corpus_version_suppressed_chunk;
        DROP POLICY tenant_corpus_version ON kb.corpus_version;
        DROP TRIGGER immutable_kb_corpus_publication_event
          ON kb.corpus_publication_event;
        DROP TRIGGER immutable_kb_corpus_version_suppressed_chunk
          ON kb.corpus_version_suppressed_chunk;
        DROP TABLE kb.corpus_publication_event;
        DROP TABLE kb.corpus_version_suppressed_chunk;
        DROP TABLE kb.corpus_version;
        """
    )
