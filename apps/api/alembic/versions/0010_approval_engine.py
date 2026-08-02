"""Add version-pinned, concurrency-safe approval runtime state."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0014

from collections.abc import Sequence

from alembic import op

revision: str = "0010_approval_engine"
down_revision: str | None = "0009_business_calendar_sla"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE config.approval_definition_version
          ADD COLUMN allow_requester_self_approval boolean NOT NULL DEFAULT false,
          ADD COLUMN expires_after_minutes integer,
          ADD CONSTRAINT approval_definition_expiry_ck CHECK (
            expires_after_minutes IS NULL OR expires_after_minutes > 0
          );

        ALTER TABLE itsm.ticket_approval
          ADD COLUMN row_version integer NOT NULL DEFAULT 1,
          ADD COLUMN expires_at timestamptz,
          ADD CONSTRAINT ticket_approval_row_version_ck CHECK (row_version > 0),
          ADD CONSTRAINT ticket_approval_temporal_ck CHECK (
            (completed_at IS NULL OR completed_at >= requested_at) AND
            (expires_at IS NULL OR expires_at > requested_at)
          ),
          ADD CONSTRAINT ticket_approval_id_tenant_ux UNIQUE
            (ticket_approval_id, tenant_id);

        CREATE UNIQUE INDEX ticket_approval_pending_definition_ux
          ON itsm.ticket_approval(ticket_id, approval_definition_id)
          WHERE approval_status = 'PENDING';
        CREATE INDEX ticket_approval_pending_expiry_ix
          ON itsm.ticket_approval(tenant_id, expires_at, ticket_approval_id)
          WHERE approval_status = 'PENDING' AND expires_at IS NOT NULL;

        ALTER TABLE itsm.ticket_approver
          ADD COLUMN tenant_id uuid;
        UPDATE itsm.ticket_approver AS approver
          SET tenant_id = approval.tenant_id
          FROM itsm.ticket_approval AS approval
          WHERE approval.ticket_approval_id = approver.ticket_approval_id;
        ALTER TABLE itsm.ticket_approver
          ALTER COLUMN tenant_id SET NOT NULL,
          ADD CONSTRAINT ticket_approver_tenant_fk FOREIGN KEY
            (ticket_approval_id, tenant_id)
            REFERENCES itsm.ticket_approval(ticket_approval_id, tenant_id)
            ON DELETE CASCADE,
          ADD CONSTRAINT ticket_approver_decision_state_ck CHECK (
            (decision_code IS NULL AND decision_comment IS NULL AND decided_at IS NULL) OR
            (decision_code IS NOT NULL AND decided_at IS NOT NULL)
          );
        CREATE INDEX ticket_approver_user_pending_ix
          ON itsm.ticket_approver(tenant_id, approver_user_id, ticket_approval_id)
          WHERE decision_code IS NULL;

        ALTER TABLE itsm.ticket_approval_decision
          ADD CONSTRAINT ticket_approval_decision_tenant_fk FOREIGN KEY
            (ticket_approval_id, tenant_id)
            REFERENCES itsm.ticket_approval(ticket_approval_id, tenant_id)
            ON DELETE CASCADE,
          ADD CONSTRAINT ticket_approval_decision_once_ux UNIQUE
            (ticket_approval_id, approver_user_id);

        CREATE FUNCTION util.approval_rls_active()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
          SELECT c.relrowsecurity
          FROM pg_class AS c
          JOIN pg_namespace AS n ON n.oid=c.relnamespace
          WHERE n.nspname='itsm' AND c.relname='ticket_approval'
        $$;
        REVOKE ALL ON FUNCTION util.approval_rls_active() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION util.approval_rls_active()
          TO helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;

        ALTER TABLE itsm.ticket_approver ENABLE ROW LEVEL SECURITY;
        ALTER TABLE itsm.ticket_approval_decision ENABLE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation_ticket_approver ON itsm.ticket_approver
          USING (
            NOT util.approval_rls_active() OR tenant_id = util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id = util.current_tenant_id()
          );
        CREATE POLICY tenant_isolation_ticket_approval_decision
          ON itsm.ticket_approval_decision
          USING (
            NOT util.approval_rls_active() OR tenant_id = util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id = util.current_tenant_id()
          );

        REVOKE DELETE ON itsm.ticket_approval, itsm.ticket_approver,
          itsm.ticket_approval_decision
          FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY tenant_isolation_ticket_approval_decision
          ON itsm.ticket_approval_decision;
        DROP POLICY tenant_isolation_ticket_approver ON itsm.ticket_approver;
        ALTER TABLE itsm.ticket_approval_decision DISABLE ROW LEVEL SECURITY;
        ALTER TABLE itsm.ticket_approver DISABLE ROW LEVEL SECURITY;
        REVOKE EXECUTE ON FUNCTION util.approval_rls_active()
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        DROP FUNCTION util.approval_rls_active();

        ALTER TABLE itsm.ticket_approval_decision
          DROP CONSTRAINT ticket_approval_decision_once_ux,
          DROP CONSTRAINT ticket_approval_decision_tenant_fk;

        DROP INDEX itsm.ticket_approver_user_pending_ix;
        ALTER TABLE itsm.ticket_approver
          DROP CONSTRAINT ticket_approver_decision_state_ck,
          DROP CONSTRAINT ticket_approver_tenant_fk,
          DROP COLUMN tenant_id;

        DROP INDEX itsm.ticket_approval_pending_expiry_ix;
        DROP INDEX itsm.ticket_approval_pending_definition_ux;
        ALTER TABLE itsm.ticket_approval
          DROP CONSTRAINT ticket_approval_id_tenant_ux,
          DROP CONSTRAINT ticket_approval_temporal_ck,
          DROP CONSTRAINT ticket_approval_row_version_ck,
          DROP COLUMN expires_at,
          DROP COLUMN row_version;

        ALTER TABLE config.approval_definition_version
          DROP CONSTRAINT approval_definition_expiry_ck,
          DROP COLUMN expires_after_minutes,
          DROP COLUMN allow_requester_self_approval;
        """
    )
