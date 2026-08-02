"""Add idempotent business-calendar and SLA runtime support."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0013

from collections.abc import Sequence

from alembic import op

revision: str = "0009_business_calendar_sla"
down_revision: str | None = "0008_attachment_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE itsm.ticket_sla
          DROP CONSTRAINT ticket_sla_state_ck,
          ADD CONSTRAINT ticket_sla_state_ck CHECK (
            state_code IN ('PENDING','RUNNING','PAUSED','COMPLETED','BREACHED','CANCELLED')
          ),
          ADD COLUMN warning_at timestamptz,
          ADD COLUMN warning_emitted_at timestamptz,
          ADD COLUMN row_version integer NOT NULL DEFAULT 1,
          ADD CONSTRAINT ticket_sla_row_version_ck CHECK (row_version > 0),
          ADD CONSTRAINT ticket_sla_temporal_ck CHECK (
            (paused_at IS NULL OR paused_at >= started_at) AND
            (completed_at IS NULL OR completed_at >= started_at) AND
            (breached_at IS NULL OR breached_at >= started_at) AND
            last_calculated_at >= started_at
          ),
          ADD CONSTRAINT ticket_sla_remaining_ck CHECK (
            elapsed_working_seconds >= 0 AND
            accumulated_pause_seconds >= 0 AND
            (remaining_working_seconds IS NULL OR remaining_working_seconds >= 0)
          );

        ALTER TABLE itsm.ticket_sla_event
          DROP CONSTRAINT ticket_sla_event_type_ck,
          ADD COLUMN event_key varchar(200),
          ADD CONSTRAINT ticket_sla_event_type_ck CHECK (
            event_type IN (
              'STARTED','PAUSED','RESUMED','STOPPED','MET','WARNING','BREACHED',
              'COMPLETED','CANCELLED','RECALCULATED'
            )
          );

        UPDATE itsm.ticket_sla_event
          SET event_key = 'legacy:' || ticket_sla_event_id::text
          WHERE event_key IS NULL;

        ALTER TABLE itsm.ticket_sla_event
          ALTER COLUMN event_key SET NOT NULL;

        CREATE UNIQUE INDEX ticket_sla_event_key_ux
          ON itsm.ticket_sla_event(ticket_sla_id, event_key);
        CREATE UNIQUE INDEX ticket_sla_terminal_event_ux
          ON itsm.ticket_sla_event(ticket_sla_id, event_type)
          WHERE event_type IN ('WARNING','BREACHED');
        CREATE INDEX ticket_sla_due_work_ix
          ON itsm.ticket_sla(tenant_id, target_at, warning_at, ticket_sla_id)
          WHERE state_code = 'RUNNING';

        ALTER TABLE integration.outbox_event
          ADD COLUMN deduplication_key varchar(255);
        CREATE UNIQUE INDEX outbox_deduplication_ux
          ON integration.outbox_event(
            (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)),
            event_type,
            deduplication_key
          )
          WHERE deduplication_key IS NOT NULL;
        CREATE INDEX outbox_sla_pending_ix
          ON integration.outbox_event(available_at, created_at, outbox_event_id)
          WHERE status_code IN ('PENDING','FAILED')
            AND event_type IN (
              'START_SLA','AGENT_PUBLIC_RESPONSE_ADDED','CUSTOMER_COMMENT_ADDED',
              'TICKET_WORKFLOW_TRANSITIONED','TICKET_PRIORITY_CHANGED'
            );

        CREATE FUNCTION util.protect_published_calendar_child()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          parent_version_id uuid;
          parent_status varchar(20);
        BEGIN
          IF TG_OP = 'DELETE' THEN
            parent_version_id := OLD.business_calendar_version_id;
          ELSE
            parent_version_id := NEW.business_calendar_version_id;
          END IF;
          SELECT version_status INTO parent_status
          FROM config.business_calendar_version
          WHERE business_calendar_version_id = parent_version_id;
          IF parent_status IN ('PUBLISHED','RETIRED') THEN
            RAISE EXCEPTION 'Published or retired business calendar versions are immutable'
              USING ERRCODE = '55000';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$;

        CREATE TRIGGER calendar_working_period_protect_published
          BEFORE INSERT OR UPDATE OR DELETE ON config.calendar_working_period
          FOR EACH ROW EXECUTE FUNCTION util.protect_published_calendar_child();
        CREATE TRIGGER calendar_exception_protect_published
          BEFORE INSERT OR UPDATE OR DELETE ON config.calendar_exception
          FOR EACH ROW EXECUTE FUNCTION util.protect_published_calendar_child();

        CREATE FUNCTION itsm.record_first_response(
          p_tenant_id uuid,
          p_ticket_id uuid,
          p_responded_at timestamptz
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, itsm
        AS $$
        DECLARE
          affected_rows integer;
        BEGIN
          IF p_tenant_id IS DISTINCT FROM util.current_tenant_id() THEN
            RAISE EXCEPTION 'Tenant context does not match requested tenant'
              USING ERRCODE = '42501';
          END IF;

          UPDATE itsm.ticket
          SET first_response_at = p_responded_at,
              updated_at = clock_timestamp(),
              row_version = row_version + 1
          WHERE tenant_id = p_tenant_id
            AND ticket_id = p_ticket_id
            AND first_response_at IS NULL;
          GET DIAGNOSTICS affected_rows = ROW_COUNT;
          RETURN affected_rows > 0;
        END;
        $$;
        REVOKE ALL ON FUNCTION itsm.record_first_response(uuid,uuid,timestamptz)
          FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION itsm.record_first_response(uuid,uuid,timestamptz)
          TO helpdesk_worker;

        CREATE FUNCTION itsm.record_sla_event(
          p_ticket_sla_id uuid,
          p_event_type varchar,
          p_event_at timestamptz,
          p_event_key varchar,
          p_event_data jsonb
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, itsm
        AS $$
        DECLARE
          event_recorded boolean := false;
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM itsm.ticket_sla
            WHERE ticket_sla_id = p_ticket_sla_id
              AND tenant_id = util.current_tenant_id()
          ) THEN
            RAISE EXCEPTION 'SLA event tenant context does not match runtime state'
              USING ERRCODE = '42501';
          END IF;

          INSERT INTO itsm.ticket_sla_event(
            ticket_sla_id,event_type,event_at,event_key,event_data_json
          ) VALUES (
            p_ticket_sla_id,p_event_type,p_event_at,p_event_key,p_event_data
          )
          ON CONFLICT (ticket_sla_id,event_key) DO NOTHING
          RETURNING true INTO event_recorded;
          RETURN COALESCE(event_recorded, false);
        END;
        $$;
        REVOKE ALL ON FUNCTION itsm.record_sla_event(uuid,varchar,timestamptz,varchar,jsonb)
          FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
          itsm.record_sla_event(uuid,varchar,timestamptz,varchar,jsonb)
          TO helpdesk_worker;

        GRANT INSERT, UPDATE ON itsm.ticket_sla TO helpdesk_worker;
        REVOKE INSERT ON itsm.ticket_sla_event FROM helpdesk_worker;
        REVOKE DELETE ON itsm.ticket_sla, itsm.ticket_sla_event
          FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE INSERT, UPDATE ON itsm.ticket_sla FROM helpdesk_worker;
        REVOKE EXECUTE ON FUNCTION
          itsm.record_sla_event(uuid,varchar,timestamptz,varchar,jsonb)
          FROM helpdesk_worker;
        DROP FUNCTION itsm.record_sla_event(uuid,varchar,timestamptz,varchar,jsonb);
        REVOKE EXECUTE ON FUNCTION itsm.record_first_response(uuid,uuid,timestamptz)
          FROM helpdesk_worker;
        DROP FUNCTION itsm.record_first_response(uuid,uuid,timestamptz);

        DROP TRIGGER calendar_exception_protect_published ON config.calendar_exception;
        DROP TRIGGER calendar_working_period_protect_published
          ON config.calendar_working_period;
        DROP FUNCTION util.protect_published_calendar_child();

        DROP INDEX integration.outbox_sla_pending_ix;
        DROP INDEX integration.outbox_deduplication_ux;
        ALTER TABLE integration.outbox_event DROP COLUMN deduplication_key;

        DROP INDEX itsm.ticket_sla_due_work_ix;
        DROP INDEX itsm.ticket_sla_terminal_event_ux;
        DROP INDEX itsm.ticket_sla_event_key_ux;
        ALTER TABLE itsm.ticket_sla_event
          DROP CONSTRAINT ticket_sla_event_type_ck,
          DROP COLUMN event_key,
          ADD CONSTRAINT ticket_sla_event_type_ck CHECK (
            event_type IN (
              'STARTED','PAUSED','RESUMED','WARNING','BREACHED',
              'COMPLETED','CANCELLED','RECALCULATED'
            )
          );

        ALTER TABLE itsm.ticket_sla
          DROP CONSTRAINT ticket_sla_remaining_ck,
          DROP CONSTRAINT ticket_sla_temporal_ck,
          DROP CONSTRAINT ticket_sla_row_version_ck,
          DROP COLUMN row_version,
          DROP COLUMN warning_emitted_at,
          DROP COLUMN warning_at,
          DROP CONSTRAINT ticket_sla_state_ck,
          ADD CONSTRAINT ticket_sla_state_ck CHECK (
            state_code IN ('RUNNING','PAUSED','COMPLETED','BREACHED','CANCELLED')
          );
        """
    )
