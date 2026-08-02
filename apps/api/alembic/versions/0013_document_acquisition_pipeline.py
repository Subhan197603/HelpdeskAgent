"""Add resumable document acquisition and quarantine state."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0017

from collections.abc import Sequence

from alembic import op

revision: str = "0013_document_acquisition"
down_revision: str | None = "0012_knowledge_source_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.ingestion_manifest_entry
          ADD COLUMN original_filename varchar(255),
          ADD COLUMN declared_content_type varchar(150),
          ADD COLUMN declared_size_bytes bigint,
          ADD COLUMN source_last_modified_at timestamptz,
          ADD COLUMN copyright_notice text,
          ADD COLUMN approved_by uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN approved_at timestamptz,
          ADD COLUMN row_version integer NOT NULL DEFAULT 1,
          ADD CONSTRAINT manifest_filename_ck CHECK (
            original_filename IS NULL OR (
              length(trim(original_filename))>0 AND original_filename !~ '[\\/\\r\\n]'
            )
          ),
          ADD CONSTRAINT manifest_declared_size_ck CHECK (
            declared_size_bytes IS NULL OR declared_size_bytes>0
          ),
          ADD CONSTRAINT manifest_expected_sha256_ck CHECK (
            expected_sha256 IS NULL OR expected_sha256 ~ '^[0-9a-f]{64}$'
          ),
          ADD CONSTRAINT manifest_approval_actor_ck CHECK (
            acquisition_permission<>'APPROVED'
            OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)
          ) NOT VALID,
          ADD CONSTRAINT manifest_row_version_ck CHECK (row_version>0);

        ALTER TABLE kb.ingestion_run
          ADD COLUMN correlation_id uuid,
          ADD COLUMN request_id varchar(200),
          ADD COLUMN row_version integer NOT NULL DEFAULT 1,
          ADD CONSTRAINT ingestion_run_counts_ck CHECK (
            total_items>=0 AND completed_items>=0 AND failed_items>=0
            AND completed_items+failed_items<=total_items
          ) NOT VALID,
          ADD CONSTRAINT ingestion_run_row_version_ck CHECK (row_version>0),
          ADD CONSTRAINT ingestion_run_tenant_ux UNIQUE (ingestion_run_id,tenant_id);

        ALTER TABLE kb.ingestion_run_item
          DROP CONSTRAINT ingestion_item_status_ck,
          ADD COLUMN tenant_id uuid REFERENCES identity.tenant(tenant_id),
          ADD COLUMN source_row_version integer,
          ADD COLUMN manifest_entry_row_version integer,
          ADD COLUMN permission_reference_snapshot text,
          ADD COLUMN quarantine_object_key text,
          ADD COLUMN original_filename varchar(255),
          ADD COLUMN declared_content_type varchar(150),
          ADD COLUMN detected_content_type varchar(150),
          ADD COLUMN file_size_bytes bigint,
          ADD COLUMN malware_scan_status varchar(20) NOT NULL DEFAULT 'PENDING',
          ADD COLUMN malware_scanned_at timestamptz,
          ADD COLUMN scanner_engine varchar(100),
          ADD COLUMN scanner_version varchar(100),
          ADD COLUMN threat_name text,
          ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN final_failure boolean NOT NULL DEFAULT false,
          ADD COLUMN locked_at timestamptz,
          ADD COLUMN locked_by varchar(200),
          ADD COLUMN row_version integer NOT NULL DEFAULT 1;

        UPDATE kb.ingestion_run_item AS item SET tenant_id=run.tenant_id
        FROM kb.ingestion_run AS run
        WHERE run.ingestion_run_id=item.ingestion_run_id;

        ALTER TABLE kb.ingestion_run_item
          ALTER COLUMN tenant_id SET NOT NULL,
          ADD CONSTRAINT ingestion_item_run_tenant_fk FOREIGN KEY
            (ingestion_run_id,tenant_id)
            REFERENCES kb.ingestion_run(ingestion_run_id,tenant_id) ON DELETE CASCADE,
          ADD CONSTRAINT ingestion_item_status_ck CHECK (
            item_status IN (
              'AWAITING_UPLOAD','QUEUED','ACQUIRING','ACQUIRED','EXTRACTING','EXTRACTED',
              'CHUNKING','CHUNKED','EMBEDDING','EMBEDDED','VALIDATING','PUBLISHED',
              'SKIPPED_UNCHANGED','BLOCKED_PERMISSION','FAILED'
            )
          ),
          ADD CONSTRAINT ingestion_item_source_version_ck CHECK (
            source_row_version IS NULL OR source_row_version>0
          ),
          ADD CONSTRAINT ingestion_item_manifest_version_ck CHECK (
            manifest_entry_row_version IS NULL OR manifest_entry_row_version>0
          ),
          ADD CONSTRAINT ingestion_item_size_ck CHECK (
            file_size_bytes IS NULL OR file_size_bytes>0
          ),
          ADD CONSTRAINT ingestion_item_checksum_ck CHECK (
            observed_sha256 IS NULL OR observed_sha256 ~ '^[0-9a-f]{64}$'
          ),
          ADD CONSTRAINT ingestion_item_scan_status_ck CHECK (
            malware_scan_status IN ('PENDING','SCANNING','CLEAN','INFECTED','ERROR')
          ),
          ADD CONSTRAINT ingestion_item_filename_ck CHECK (
            original_filename IS NULL OR (
              length(trim(original_filename))>0 AND original_filename !~ '[\\/\\r\\n]'
            )
          ),
          ADD CONSTRAINT ingestion_item_row_version_ck CHECK (row_version>0);

        CREATE INDEX ingestion_run_item_due_ix ON kb.ingestion_run_item(
          item_status,final_failure,next_attempt_at,created_at
        ) WHERE item_status IN ('QUEUED','FAILED');
        CREATE INDEX document_version_checksum_ix
          ON kb.document_version(sha256_checksum,document_id);

        CREATE TABLE kb.ingestion_event (
          ingestion_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          ingestion_run_id uuid NOT NULL,
          ingestion_run_item_id uuid NOT NULL REFERENCES kb.ingestion_run_item(
            ingestion_run_item_id
          ) ON DELETE CASCADE,
          event_code varchar(80) NOT NULL,
          outcome_code varchar(20) NOT NULL CHECK (
            outcome_code IN ('SUCCESS','BLOCKED','RETRYABLE_FAILURE','FINAL_FAILURE')
          ),
          detail_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          deduplication_key varchar(250) NOT NULL,
          occurred_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (ingestion_run_id,tenant_id)
            REFERENCES kb.ingestion_run(ingestion_run_id,tenant_id) ON DELETE CASCADE,
          UNIQUE (ingestion_run_item_id,deduplication_key)
        );
        CREATE TRIGGER immutable_kb_ingestion_event
          BEFORE UPDATE OR DELETE ON kb.ingestion_event
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        CREATE FUNCTION kb.claim_acquisition_item(p_worker_id varchar)
        RETURNS TABLE(ingestion_run_item_id uuid,tenant_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog,kb
        AS $$
        BEGIN
          RETURN QUERY
          WITH candidate AS (
            SELECT item.ingestion_run_item_id
            FROM kb.ingestion_run_item AS item
            WHERE NOT item.final_failure
              AND item.item_status IN ('QUEUED','FAILED')
              AND item.next_attempt_at<=clock_timestamp()
              AND (
                item.locked_at IS NULL
                OR item.locked_at<clock_timestamp()-interval '5 minutes'
              )
            ORDER BY item.next_attempt_at,item.created_at,item.ingestion_run_item_id
            FOR UPDATE SKIP LOCKED LIMIT 1
          )
          UPDATE kb.ingestion_run_item AS item
          SET item_status='ACQUIRING',attempt_count=item.attempt_count+1,
            started_at=coalesce(item.started_at,clock_timestamp()),
            locked_at=clock_timestamp(),locked_by=p_worker_id,error_code=NULL,
            error_message=NULL,row_version=item.row_version+1
          FROM candidate
          WHERE item.ingestion_run_item_id=candidate.ingestion_run_item_id
          RETURNING item.ingestion_run_item_id,item.tenant_id;
        END;
        $$;
        REVOKE ALL ON FUNCTION kb.claim_acquisition_item(varchar) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION kb.claim_acquisition_item(varchar) TO helpdesk_worker;

        ALTER TABLE kb.ingestion_manifest_entry ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.ingestion_run ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.ingestion_run_item ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.ingestion_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_or_global_manifest ON kb.ingestion_manifest_entry
          USING (
            NOT util.approval_rls_active() OR tenant_id IS NULL
            OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id IS NULL
            OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_ingestion_run ON kb.ingestion_run
          USING (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_ingestion_run_item ON kb.ingestion_run_item
          USING (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_ingestion_event ON kb.ingestion_event
          USING (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,INSERT,UPDATE ON kb.ingestion_manifest_entry,kb.ingestion_run,
          kb.ingestion_run_item TO helpdesk_app;
        GRANT SELECT ON kb.source_acquisition_authorization TO helpdesk_worker;
        GRANT SELECT,INSERT,UPDATE ON kb.document,kb.document_version,
          kb.ingestion_run,kb.ingestion_run_item TO helpdesk_worker;
        GRANT SELECT,INSERT ON kb.ingestion_event TO helpdesk_app,helpdesk_worker;
        REVOKE DELETE ON kb.ingestion_manifest_entry,kb.ingestion_run,
          kb.ingestion_run_item,kb.ingestion_event,kb.document,kb.document_version
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.ingestion_event
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_ingestion_event ON kb.ingestion_event;
        DROP POLICY tenant_ingestion_run_item ON kb.ingestion_run_item;
        DROP POLICY tenant_ingestion_run ON kb.ingestion_run;
        DROP POLICY tenant_or_global_manifest ON kb.ingestion_manifest_entry;
        DROP FUNCTION kb.claim_acquisition_item(varchar);
        DROP TABLE kb.ingestion_event;
        DROP INDEX kb.document_version_checksum_ix;
        DROP INDEX kb.ingestion_run_item_due_ix;
        ALTER TABLE kb.ingestion_run_item
          DROP CONSTRAINT ingestion_item_row_version_ck,
          DROP CONSTRAINT ingestion_item_filename_ck,
          DROP CONSTRAINT ingestion_item_scan_status_ck,
          DROP CONSTRAINT ingestion_item_checksum_ck,
          DROP CONSTRAINT ingestion_item_size_ck,
          DROP CONSTRAINT ingestion_item_manifest_version_ck,
          DROP CONSTRAINT ingestion_item_source_version_ck,
          DROP CONSTRAINT ingestion_item_status_ck,
          DROP CONSTRAINT ingestion_item_run_tenant_fk,
          DROP COLUMN row_version,
          DROP COLUMN locked_by,
          DROP COLUMN locked_at,
          DROP COLUMN final_failure,
          DROP COLUMN next_attempt_at,
          DROP COLUMN threat_name,
          DROP COLUMN scanner_version,
          DROP COLUMN scanner_engine,
          DROP COLUMN malware_scanned_at,
          DROP COLUMN malware_scan_status,
          DROP COLUMN file_size_bytes,
          DROP COLUMN detected_content_type,
          DROP COLUMN declared_content_type,
          DROP COLUMN original_filename,
          DROP COLUMN quarantine_object_key,
          DROP COLUMN permission_reference_snapshot,
          DROP COLUMN manifest_entry_row_version,
          DROP COLUMN source_row_version,
          DROP COLUMN tenant_id,
          ADD CONSTRAINT ingestion_item_status_ck CHECK (
            item_status IN (
              'QUEUED','ACQUIRING','ACQUIRED','EXTRACTING','EXTRACTED','CHUNKING',
              'CHUNKED','EMBEDDING','EMBEDDED','VALIDATING','PUBLISHED',
              'SKIPPED_UNCHANGED','BLOCKED_PERMISSION','FAILED'
            )
          );
        ALTER TABLE kb.ingestion_run
          DROP CONSTRAINT ingestion_run_tenant_ux,
          DROP CONSTRAINT ingestion_run_row_version_ck,
          DROP CONSTRAINT ingestion_run_counts_ck,
          DROP COLUMN row_version,
          DROP COLUMN request_id,
          DROP COLUMN correlation_id;
        ALTER TABLE kb.ingestion_manifest_entry
          DROP CONSTRAINT manifest_row_version_ck,
          DROP CONSTRAINT manifest_approval_actor_ck,
          DROP CONSTRAINT manifest_expected_sha256_ck,
          DROP CONSTRAINT manifest_declared_size_ck,
          DROP CONSTRAINT manifest_filename_ck,
          DROP COLUMN row_version,
          DROP COLUMN approved_at,
          DROP COLUMN approved_by,
          DROP COLUMN copyright_notice,
          DROP COLUMN source_last_modified_at,
          DROP COLUMN declared_size_bytes,
          DROP COLUMN declared_content_type,
          DROP COLUMN original_filename;
        """
    )
