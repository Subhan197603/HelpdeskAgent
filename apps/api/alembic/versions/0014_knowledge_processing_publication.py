"""Add versioned knowledge processing and publication evidence."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0018

from collections.abc import Sequence

from alembic import op

revision: str = "0014_knowledge_processing"
down_revision: str | None = "0013_document_acquisition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.ingestion_run_item
          ADD COLUMN pipeline_stage varchar(20) NOT NULL DEFAULT 'ACQUISITION',
          ADD COLUMN processing_attempt_count integer NOT NULL DEFAULT 0,
          ADD COLUMN processing_next_attempt_at timestamptz NOT NULL DEFAULT now(),
          ADD CONSTRAINT ingestion_item_pipeline_stage_ck CHECK (
            pipeline_stage IN ('ACQUISITION','PROCESSING','COMPLETE')
          ),
          ADD CONSTRAINT ingestion_item_processing_attempt_ck CHECK (
            processing_attempt_count>=0
          );
        UPDATE kb.ingestion_run_item SET pipeline_stage=CASE
          WHEN item_status IN ('ACQUIRED','EXTRACTING','EXTRACTED','CHUNKING','CHUNKED',
            'EMBEDDING','EMBEDDED','VALIDATING') THEN 'PROCESSING'
          WHEN item_status IN ('PUBLISHED','SKIPPED_UNCHANGED') THEN 'COMPLETE'
          ELSE 'ACQUISITION' END;
        CREATE INDEX ingestion_run_item_processing_due_ix ON kb.ingestion_run_item(
          pipeline_stage,item_status,final_failure,processing_next_attempt_at,created_at
        ) WHERE pipeline_stage='PROCESSING';

        CREATE TABLE kb.document_processing_version (
          processing_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          document_id uuid NOT NULL REFERENCES kb.document(document_id) ON DELETE CASCADE,
          document_version_id uuid NOT NULL REFERENCES kb.document_version(
            document_version_id
          ) ON DELETE CASCADE,
          processing_number integer NOT NULL CHECK (processing_number>0),
          parser_name varchar(100) NOT NULL,
          parser_version varchar(50) NOT NULL,
          chunker_name varchar(100) NOT NULL,
          chunker_version varchar(50) NOT NULL,
          chunking_configuration_json jsonb NOT NULL,
          chunking_configuration_hash varchar(64) NOT NULL CHECK (
            chunking_configuration_hash ~ '^[0-9a-f]{64}$'
          ),
          embedding_model_code varchar(100) NOT NULL REFERENCES kb.embedding_model(
            embedding_model_code
          ),
          embedding_configuration_version_id uuid REFERENCES
            kb.embedding_configuration_version(embedding_configuration_version_id),
          processing_status varchar(20) NOT NULL DEFAULT 'RUNNING' CHECK (
            processing_status IN ('RUNNING','COMPLETED','FAILED','SUPERSEDED')
          ),
          normalized_object_key text,
          extracted_text_sha256 varchar(64) CHECK (
            extracted_text_sha256 IS NULL OR extracted_text_sha256 ~ '^[0-9a-f]{64}$'
          ),
          page_count integer CHECK (page_count IS NULL OR page_count>=0),
          chunk_count integer CHECK (chunk_count IS NULL OR chunk_count>=0),
          embedded_chunk_count integer CHECK (
            embedded_chunk_count IS NULL OR embedded_chunk_count>=0
          ),
          validation_status varchar(20) NOT NULL DEFAULT 'PENDING' CHECK (
            validation_status IN ('PENDING','PASSED','WARNING','FAILED')
          ),
          validation_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (document_version_id,processing_number),
          UNIQUE (document_version_id,parser_name,parser_version,
            chunker_name,chunker_version,chunking_configuration_hash,
            embedding_model_code)
        );

        ALTER TABLE kb.document_chunk
          DROP CONSTRAINT document_chunk_document_version_id_chunk_sequence_key,
          DROP CONSTRAINT document_chunk_document_version_id_content_hash_key,
          ADD COLUMN processing_version_id uuid REFERENCES kb.document_processing_version(
            processing_version_id
          ) ON DELETE CASCADE,
          ADD COLUMN tenant_id uuid REFERENCES identity.tenant(tenant_id),
          ADD COLUMN document_id uuid REFERENCES kb.document(document_id) ON DELETE CASCADE,
          ADD COLUMN source_id uuid REFERENCES kb.source(source_id),
          ADD COLUMN audience_code varchar(30),
          ADD COLUMN security_classification varchar(30),
          ADD COLUMN embedding_input_hash varchar(64);

        INSERT INTO kb.document_processing_version(
          tenant_id,document_id,document_version_id,processing_number,parser_name,
          parser_version,chunker_name,chunker_version,chunking_configuration_json,
          chunking_configuration_hash,embedding_model_code,processing_status,
          chunk_count,validation_status,completed_at)
        SELECT d.tenant_id,d.document_id,dv.document_version_id,1,
          coalesce(dv.parser_name,'LEGACY'),coalesce(dv.parser_version,'0'),
          'LEGACY','0','{}'::jsonb,
          encode(digest('legacy','sha256'),'hex'),'DEFAULT_1536','COMPLETED',
          count(c.chunk_id),dv.validation_status,now()
        FROM kb.document_chunk c
        JOIN kb.document_version dv ON dv.document_version_id=c.document_version_id
        JOIN kb.document d ON d.document_id=dv.document_id
        WHERE d.tenant_id IS NOT NULL
        GROUP BY d.tenant_id,d.document_id,dv.document_version_id,dv.parser_name,
          dv.parser_version,dv.validation_status;

        UPDATE kb.document_chunk c SET
          processing_version_id=p.processing_version_id,
          tenant_id=p.tenant_id,
          document_id=p.document_id,
          source_id=d.source_id,
          audience_code=d.audience_code,
          security_classification=d.security_classification,
          embedding_input_hash=encode(digest(c.content_text,'sha256'),'hex')
        FROM kb.document_processing_version p,kb.document d
        WHERE p.document_version_id=c.document_version_id
          AND d.document_id=p.document_id;

        ALTER TABLE kb.document_chunk
          ALTER COLUMN processing_version_id SET NOT NULL,
          ALTER COLUMN tenant_id SET NOT NULL,
          ALTER COLUMN document_id SET NOT NULL,
          ALTER COLUMN source_id SET NOT NULL,
          ALTER COLUMN audience_code SET NOT NULL,
          ALTER COLUMN security_classification SET NOT NULL,
          ALTER COLUMN embedding_input_hash SET NOT NULL,
          ADD CONSTRAINT document_chunk_audience_ck CHECK (
            audience_code IN ('EMPLOYEE','ANALYST','TECHNICAL_SPECIALIST','ADMIN','ALL')
          ),
          ADD CONSTRAINT document_chunk_security_ck CHECK (
            security_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')
          ),
          ADD CONSTRAINT document_chunk_embedding_hash_ck CHECK (
            embedding_input_hash ~ '^[0-9a-f]{64}$'
          ),
          ADD CONSTRAINT document_chunk_processing_sequence_ux UNIQUE (
            processing_version_id,chunk_sequence
          ),
          ADD CONSTRAINT document_chunk_processing_hash_ux UNIQUE (
            processing_version_id,content_hash
          );

        ALTER TABLE kb.document_version
          ADD COLUMN published_processing_version_id uuid REFERENCES
            kb.document_processing_version(processing_version_id),
          ADD COLUMN published_at timestamptz,
          ADD COLUMN retired_at timestamptz,
          ADD CONSTRAINT document_version_publication_ck CHECK (
            (current_version_flag=false) OR (
              validation_status IN ('PASSED','WARNING')
              AND published_processing_version_id IS NOT NULL
              AND published_at IS NOT NULL
            )
          ) NOT VALID;

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

        ALTER TABLE kb.chunk_embedding_1536
          ADD COLUMN tenant_id uuid REFERENCES identity.tenant(tenant_id),
          ADD COLUMN processing_version_id uuid REFERENCES kb.document_processing_version(
            processing_version_id
          ) ON DELETE CASCADE;
        UPDATE kb.chunk_embedding_1536 e SET
          tenant_id=c.tenant_id,processing_version_id=c.processing_version_id
        FROM kb.document_chunk c WHERE c.chunk_id=e.chunk_id;
        ALTER TABLE kb.chunk_embedding_1536
          ALTER COLUMN tenant_id SET NOT NULL,
          ALTER COLUMN processing_version_id SET NOT NULL;

        ALTER TABLE kb.document
          ADD COLUMN row_version integer NOT NULL DEFAULT 1,
          ADD CONSTRAINT document_row_version_ck CHECK (row_version>0);

        CREATE TABLE kb.document_publication_event (
          publication_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          document_id uuid NOT NULL REFERENCES kb.document(document_id),
          document_version_id uuid NOT NULL REFERENCES kb.document_version(
            document_version_id
          ),
          processing_version_id uuid NOT NULL REFERENCES kb.document_processing_version(
            processing_version_id
          ),
          action_code varchar(20) NOT NULL CHECK (action_code IN ('PUBLISHED','RETIRED')),
          actor_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
          previous_document_version_id uuid REFERENCES kb.document_version(document_version_id),
          evidence_json jsonb NOT NULL,
          correlation_id uuid,
          request_id varchar(200),
          deduplication_key varchar(250) NOT NULL,
          occurred_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id,deduplication_key)
        );
        CREATE TRIGGER immutable_kb_document_publication_event
          BEFORE UPDATE OR DELETE ON kb.document_publication_event
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        CREATE OR REPLACE FUNCTION kb.claim_acquisition_item(p_worker_id varchar)
        RETURNS TABLE(ingestion_run_item_id uuid,tenant_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,kb AS $$
        BEGIN
          RETURN QUERY
          WITH candidate AS (
            SELECT item.ingestion_run_item_id FROM kb.ingestion_run_item item
            WHERE item.pipeline_stage='ACQUISITION' AND NOT item.final_failure
              AND item.item_status IN ('QUEUED','FAILED')
              AND item.next_attempt_at<=clock_timestamp()
              AND (item.locked_at IS NULL OR
                item.locked_at<clock_timestamp()-interval '5 minutes')
            ORDER BY item.next_attempt_at,item.created_at,item.ingestion_run_item_id
            FOR UPDATE SKIP LOCKED LIMIT 1
          )
          UPDATE kb.ingestion_run_item item
          SET item_status='ACQUIRING',attempt_count=item.attempt_count+1,
            started_at=coalesce(item.started_at,clock_timestamp()),
            locked_at=clock_timestamp(),locked_by=p_worker_id,error_code=NULL,
            error_message=NULL,row_version=item.row_version+1
          FROM candidate WHERE item.ingestion_run_item_id=candidate.ingestion_run_item_id
          RETURNING item.ingestion_run_item_id,item.tenant_id;
        END; $$;

        CREATE FUNCTION kb.claim_processing_item(p_worker_id varchar)
        RETURNS TABLE(ingestion_run_item_id uuid,tenant_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,kb AS $$
        BEGIN
          RETURN QUERY
          WITH candidate AS (
            SELECT item.ingestion_run_item_id FROM kb.ingestion_run_item item
            WHERE item.pipeline_stage='PROCESSING' AND NOT item.final_failure
              AND item.item_status IN ('ACQUIRED','FAILED')
              AND item.processing_next_attempt_at<=clock_timestamp()
              AND (item.locked_at IS NULL OR
                item.locked_at<clock_timestamp()-interval '5 minutes')
            ORDER BY item.processing_next_attempt_at,item.created_at,
              item.ingestion_run_item_id
            FOR UPDATE SKIP LOCKED LIMIT 1
          )
          UPDATE kb.ingestion_run_item item
          SET item_status='EXTRACTING',processing_attempt_count=
              item.processing_attempt_count+1,
            locked_at=clock_timestamp(),locked_by=p_worker_id,error_code=NULL,
            error_message=NULL,row_version=item.row_version+1
          FROM candidate WHERE item.ingestion_run_item_id=candidate.ingestion_run_item_id
          RETURNING item.ingestion_run_item_id,item.tenant_id;
        END; $$;
        REVOKE ALL ON FUNCTION kb.claim_processing_item(varchar) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION kb.claim_processing_item(varchar) TO helpdesk_worker;

        ALTER TABLE kb.document_processing_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.document_chunk ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.chunk_embedding_1536 ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.document_publication_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_processing_version ON kb.document_processing_version
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id());
        CREATE POLICY tenant_document_chunk ON kb.document_chunk
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id());
        CREATE POLICY tenant_chunk_embedding ON kb.chunk_embedding_1536
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id());
        CREATE POLICY tenant_publication_event ON kb.document_publication_event
          USING (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id())
          WITH CHECK (NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id());

        GRANT SELECT,INSERT,UPDATE ON kb.document_processing_version,kb.document_chunk,
          kb.chunk_embedding_1536 TO helpdesk_worker;
        GRANT SELECT,UPDATE ON kb.document,kb.document_version,kb.ingestion_run_item
          TO helpdesk_app;
        GRANT SELECT ON kb.document_processing_version,kb.document_chunk,
          kb.chunk_embedding_1536 TO helpdesk_app;
        GRANT SELECT,INSERT ON kb.document_publication_event TO helpdesk_app,helpdesk_worker;
        REVOKE DELETE ON kb.document_processing_version,kb.document_chunk,
          kb.chunk_embedding_1536,kb.document_publication_event
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.document_publication_event
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_publication_event ON kb.document_publication_event;
        DROP POLICY tenant_chunk_embedding ON kb.chunk_embedding_1536;
        DROP POLICY tenant_document_chunk ON kb.document_chunk;
        DROP POLICY tenant_processing_version ON kb.document_processing_version;
        DROP FUNCTION kb.claim_processing_item(varchar);
        DROP TABLE kb.document_publication_event;
        CREATE OR REPLACE VIEW kb.v_active_document_chunk AS
        SELECT c.chunk_id,c.document_version_id,d.document_id,d.tenant_id,
          d.document_title,d.document_type,d.audience_code,d.security_classification,
          d.canonical_url,d.release_id,d.product_node_id,c.heading_path,c.chapter_title,
          c.section_title,c.section_anchor,c.page_number,c.content_text,c.search_vector,
          r.release_family,r.release_code,pn.product_code,pn.product_name,
          s.source_type,s.source_name
        FROM kb.document_chunk c
        JOIN kb.document_version dv ON dv.document_version_id=c.document_version_id
          AND dv.current_version_flag AND dv.validation_status IN ('PASSED','WARNING')
        JOIN kb.document d ON d.document_id=dv.document_id AND d.active_flag
          AND d.approval_status='APPROVED'
          AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
          AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
        JOIN kb.source s ON s.source_id=d.source_id AND s.active_flag
        LEFT JOIN kb.release r ON r.release_id=d.release_id
        LEFT JOIN kb.product_node pn ON pn.product_node_id=d.product_node_id;
        ALTER TABLE kb.document
          DROP CONSTRAINT document_row_version_ck,
          DROP COLUMN row_version;
        ALTER TABLE kb.document_version
          DROP CONSTRAINT document_version_publication_ck,
          DROP COLUMN retired_at,
          DROP COLUMN published_at,
          DROP COLUMN published_processing_version_id;
        ALTER TABLE kb.chunk_embedding_1536
          DROP COLUMN processing_version_id,
          DROP COLUMN tenant_id;
        ALTER TABLE kb.document_chunk
          DROP CONSTRAINT document_chunk_processing_hash_ux,
          DROP CONSTRAINT document_chunk_processing_sequence_ux,
          DROP CONSTRAINT document_chunk_embedding_hash_ck,
          DROP CONSTRAINT document_chunk_security_ck,
          DROP CONSTRAINT document_chunk_audience_ck,
          DROP COLUMN embedding_input_hash,
          DROP COLUMN security_classification,
          DROP COLUMN audience_code,
          DROP COLUMN source_id,
          DROP COLUMN document_id,
          DROP COLUMN tenant_id,
          DROP COLUMN processing_version_id,
          ADD CONSTRAINT document_chunk_document_version_id_chunk_sequence_key UNIQUE (
            document_version_id,chunk_sequence
          ),
          ADD CONSTRAINT document_chunk_document_version_id_content_hash_key UNIQUE (
            document_version_id,content_hash
          );
        DROP TABLE kb.document_processing_version;
        DROP INDEX kb.ingestion_run_item_processing_due_ix;
        ALTER TABLE kb.ingestion_run_item
          DROP CONSTRAINT ingestion_item_processing_attempt_ck,
          DROP CONSTRAINT ingestion_item_pipeline_stage_ck,
          DROP COLUMN processing_next_attempt_at,
          DROP COLUMN processing_attempt_count,
          DROP COLUMN pipeline_stage;
        CREATE OR REPLACE FUNCTION kb.claim_acquisition_item(p_worker_id varchar)
        RETURNS TABLE(ingestion_run_item_id uuid,tenant_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,kb AS $$
        BEGIN
          RETURN QUERY
          WITH candidate AS (
            SELECT item.ingestion_run_item_id FROM kb.ingestion_run_item item
            WHERE NOT item.final_failure AND item.item_status IN ('QUEUED','FAILED')
              AND item.next_attempt_at<=clock_timestamp()
              AND (item.locked_at IS NULL OR
                item.locked_at<clock_timestamp()-interval '5 minutes')
            ORDER BY item.next_attempt_at,item.created_at,item.ingestion_run_item_id
            FOR UPDATE SKIP LOCKED LIMIT 1
          )
          UPDATE kb.ingestion_run_item item
          SET item_status='ACQUIRING',attempt_count=item.attempt_count+1,
            started_at=coalesce(item.started_at,clock_timestamp()),
            locked_at=clock_timestamp(),locked_by=p_worker_id,error_code=NULL,
            error_message=NULL,row_version=item.row_version+1
          FROM candidate WHERE item.ingestion_run_item_id=candidate.ingestion_run_item_id
          RETURNING item.ingestion_run_item_id,item.tenant_id;
        END; $$;
        """
    )
