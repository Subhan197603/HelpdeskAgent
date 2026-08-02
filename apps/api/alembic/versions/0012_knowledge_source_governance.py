"""Add governed knowledge-source registry and acquisition permissions."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0016

from collections.abc import Sequence

from alembic import op

revision: str = "0012_knowledge_source_governance"
down_revision: str | None = "0011_notification_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.source
          ADD COLUMN canonical_location text,
          ADD COLUMN audience_scope varchar(30) NOT NULL DEFAULT 'ADMINISTRATIVE',
          ADD COLUMN source_status varchar(20) NOT NULL DEFAULT 'ACTIVE',
          ADD COLUMN approval_status varchar(20) NOT NULL DEFAULT 'DRAFT',
          ADD COLUMN owner_user_id uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN owner_group_id uuid REFERENCES identity.support_group(support_group_id),
          ADD COLUMN product_node_id uuid REFERENCES kb.product_node(product_node_id),
          ADD COLUMN module_node_id uuid REFERENCES kb.product_node(product_node_id),
          ADD COLUMN release_id uuid REFERENCES kb.release(release_id),
          ADD COLUMN language_code varchar(20) NOT NULL DEFAULT 'en',
          ADD COLUMN approved_by uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN approved_at timestamptz,
          ADD COLUMN created_by uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN updated_by uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN row_version integer NOT NULL DEFAULT 1;

        UPDATE kb.source SET
          canonical_location=coalesce(base_url,'manual:' || lower(source_code)),
          source_status=CASE WHEN active_flag THEN 'ACTIVE' ELSE 'DISABLED' END;

        ALTER TABLE kb.source
          ALTER COLUMN canonical_location SET NOT NULL,
          ADD CONSTRAINT kb_source_audience_ck CHECK (
            audience_scope IN ('EMPLOYEE','ANALYST','RESTRICTED','ADMINISTRATIVE')
          ),
          ADD CONSTRAINT kb_source_status_ck CHECK (
            source_status IN ('ACTIVE','DISABLED','RETIRED')
          ),
          ADD CONSTRAINT kb_source_approval_status_ck CHECK (
            approval_status IN ('DRAFT','UNDER_REVIEW','APPROVED','REJECTED')
          ),
          ADD CONSTRAINT kb_source_status_active_ck CHECK (
            active_flag=(source_status='ACTIVE')
          ),
          ADD CONSTRAINT kb_source_approval_actor_ck CHECK (
            (approval_status='APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
            OR (approval_status<>'APPROVED' AND approved_by IS NULL AND approved_at IS NULL)
          ),
          ADD CONSTRAINT kb_source_owner_ck CHECK (
            owner_user_id IS NOT NULL OR owner_group_id IS NOT NULL
          ) NOT VALID,
          ADD CONSTRAINT kb_source_product_module_ck CHECK (
            product_node_id IS NULL OR module_node_id IS NULL
            OR product_node_id<>module_node_id
          ),
          ADD CONSTRAINT kb_source_row_version_ck CHECK (row_version>0),
          ADD CONSTRAINT kb_source_language_ck CHECK (
            language_code ~ '^[a-z]{2,3}(-[A-Z]{2})?$'
          );

        CREATE INDEX kb_source_governance_lookup_ix
          ON kb.source(tenant_id,source_status,approval_status,audience_scope,source_code);
        CREATE INDEX kb_source_metadata_ix
          ON kb.source(release_id,product_node_id,module_node_id,language_code);

        CREATE TABLE kb.source_acquisition_authorization (
          source_acquisition_authorization_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid REFERENCES identity.tenant(tenant_id),
          source_id uuid NOT NULL REFERENCES kb.source(source_id),
          source_row_version integer NOT NULL CHECK (source_row_version>0),
          acquisition_method varchar(40) NOT NULL CHECK (
            acquisition_method IN (
              'APPROVED_DIRECT_DOWNLOAD','API_FEED','REPOSITORY_CONNECTOR'
            )
          ),
          decision_code varchar(20) NOT NULL CHECK (
            decision_code IN ('APPROVED','REVOKED')
          ),
          canonical_location text NOT NULL,
          permission_reference text NOT NULL CHECK (length(trim(permission_reference))>0),
          valid_from timestamptz NOT NULL DEFAULT now(),
          valid_to timestamptz,
          decided_by uuid NOT NULL REFERENCES identity.app_user(user_id),
          decided_at timestamptz NOT NULL DEFAULT now(),
          correlation_id uuid NOT NULL,
          request_id varchar(200) NOT NULL,
          CONSTRAINT source_acquisition_authorization_dates_ck CHECK (
            valid_to IS NULL OR valid_to>valid_from
          ),
          UNIQUE(source_id,source_row_version)
        );
        CREATE INDEX source_acquisition_authorization_effective_ix
          ON kb.source_acquisition_authorization(
            source_id,source_row_version,decision_code,valid_from,valid_to
          );
        CREATE TRIGGER immutable_kb_source_acquisition_authorization
          BEFORE UPDATE OR DELETE ON kb.source_acquisition_authorization
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        ALTER TABLE kb.source ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kb.source_acquisition_authorization ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_or_global_source ON kb.source
          USING (
            NOT util.approval_rls_active() OR tenant_id IS NULL
            OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id IS NULL
            OR tenant_id=util.current_tenant_id()
          );
        CREATE POLICY tenant_or_global_source_acquisition_authorization
          ON kb.source_acquisition_authorization
          USING (
            NOT util.approval_rls_active() OR tenant_id IS NULL
            OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id IS NULL
            OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,INSERT,UPDATE ON kb.source TO helpdesk_app;
        GRANT SELECT,INSERT ON kb.source_acquisition_authorization TO helpdesk_app;
        REVOKE DELETE ON kb.source,kb.source_acquisition_authorization
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE UPDATE ON kb.source_acquisition_authorization
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_or_global_source_acquisition_authorization
          ON kb.source_acquisition_authorization;
        DROP POLICY tenant_or_global_source ON kb.source;
        ALTER TABLE kb.source DISABLE ROW LEVEL SECURITY;
        DROP TABLE kb.source_acquisition_authorization;
        DROP INDEX kb.kb_source_metadata_ix;
        DROP INDEX kb.kb_source_governance_lookup_ix;
        ALTER TABLE kb.source
          DROP CONSTRAINT kb_source_language_ck,
          DROP CONSTRAINT kb_source_row_version_ck,
          DROP CONSTRAINT kb_source_product_module_ck,
          DROP CONSTRAINT kb_source_owner_ck,
          DROP CONSTRAINT kb_source_approval_actor_ck,
          DROP CONSTRAINT kb_source_status_active_ck,
          DROP CONSTRAINT kb_source_approval_status_ck,
          DROP CONSTRAINT kb_source_status_ck,
          DROP CONSTRAINT kb_source_audience_ck,
          DROP COLUMN row_version,
          DROP COLUMN updated_by,
          DROP COLUMN created_by,
          DROP COLUMN approved_at,
          DROP COLUMN approved_by,
          DROP COLUMN language_code,
          DROP COLUMN release_id,
          DROP COLUMN module_node_id,
          DROP COLUMN product_node_id,
          DROP COLUMN owner_group_id,
          DROP COLUMN owner_user_id,
          DROP COLUMN approval_status,
          DROP COLUMN source_status,
          DROP COLUMN audience_scope,
          DROP COLUMN canonical_location;
        """
    )
