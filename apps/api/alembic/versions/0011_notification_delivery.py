"""Add deduplicated email delivery and in-app notification state."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0015

from collections.abc import Sequence

from alembic import op

revision: str = "0011_notification_delivery"
down_revision: str | None = "0010_approval_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE integration.notification_delivery
          ADD COLUMN outbox_event_id uuid REFERENCES integration.outbox_event(outbox_event_id),
          ADD COLUMN channel_code varchar(30) NOT NULL DEFAULT 'EMAIL'
            REFERENCES config.channel(channel_code),
          ADD COLUMN recipient_user_id uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN deduplication_key varchar(255),
          ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN locked_at timestamptz,
          ADD COLUMN locked_by varchar(200),
          ADD COLUMN final_failure boolean NOT NULL DEFAULT false,
          ADD COLUMN rendered_subject text,
          ADD COLUMN rendered_body text,
          ADD CONSTRAINT notification_delivery_email_ck CHECK (
            channel_code <> 'EMAIL' OR rendered_subject IS NOT NULL
          );

        CREATE UNIQUE INDEX notification_delivery_deduplication_ux
          ON integration.notification_delivery(tenant_id,deduplication_key)
          WHERE deduplication_key IS NOT NULL;
        CREATE INDEX notification_delivery_pending_ix
          ON integration.notification_delivery(next_attempt_at,created_at,notification_delivery_id)
          WHERE delivery_status IN ('PENDING','FAILED');

        CREATE TABLE integration.notification_delivery_attempt (
          attempt_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          notification_delivery_id uuid NOT NULL
            REFERENCES integration.notification_delivery(notification_delivery_id),
          attempt_number integer NOT NULL CHECK (attempt_number > 0),
          outcome_code varchar(20) NOT NULL CHECK (
            outcome_code IN ('DELIVERED','RETRYABLE_FAILURE','PERMANENT_FAILURE')
          ),
          provider_message_id varchar(300),
          error_code varchar(100),
          attempted_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (notification_delivery_id,attempt_number)
        );

        CREATE TRIGGER immutable_integration_notification_delivery_attempt
          BEFORE UPDATE OR DELETE ON integration.notification_delivery_attempt
          FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation();

        CREATE TABLE integration.in_app_notification (
          in_app_notification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          recipient_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
          notification_template_version_id uuid NOT NULL
            REFERENCES config.notification_template_version(notification_template_version_id),
          outbox_event_id uuid NOT NULL REFERENCES integration.outbox_event(outbox_event_id),
          resource_type varchar(100) NOT NULL,
          resource_id varchar(200) NOT NULL,
          title text NOT NULL,
          body text NOT NULL,
          action_url text,
          created_at timestamptz NOT NULL DEFAULT now(),
          read_at timestamptz,
          CONSTRAINT in_app_notification_read_ck CHECK (
            read_at IS NULL OR read_at >= created_at
          ),
          UNIQUE (outbox_event_id,recipient_user_id,notification_template_version_id)
        );
        CREATE INDEX in_app_notification_user_time_ix
          ON integration.in_app_notification(
            tenant_id,recipient_user_id,created_at DESC,in_app_notification_id DESC
          );
        CREATE INDEX in_app_notification_unread_ix
          ON integration.in_app_notification(tenant_id,recipient_user_id,created_at DESC)
          WHERE read_at IS NULL;

        ALTER TABLE integration.in_app_notification ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_in_app_notification
          ON integration.in_app_notification
          USING (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          )
          WITH CHECK (
            NOT util.approval_rls_active() OR tenant_id=util.current_tenant_id()
          );

        GRANT SELECT,UPDATE ON integration.in_app_notification TO helpdesk_app;
        GRANT INSERT,SELECT ON integration.in_app_notification TO helpdesk_worker;
        GRANT INSERT,SELECT ON integration.notification_delivery_attempt TO helpdesk_worker;
        GRANT USAGE,SELECT ON SEQUENCE
          integration.notification_delivery_attempt_attempt_id_seq
          TO helpdesk_worker;
        REVOKE UPDATE,DELETE ON integration.notification_delivery_attempt
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        REVOKE DELETE ON integration.in_app_notification,integration.notification_delivery
          FROM helpdesk_app,helpdesk_worker,helpdesk_reporting,helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE integration.in_app_notification;
        DROP TABLE integration.notification_delivery_attempt;
        DROP INDEX integration.notification_delivery_pending_ix;
        DROP INDEX integration.notification_delivery_deduplication_ux;
        ALTER TABLE integration.notification_delivery
          DROP CONSTRAINT notification_delivery_email_ck,
          DROP COLUMN rendered_body,
          DROP COLUMN rendered_subject,
          DROP COLUMN locked_by,
          DROP COLUMN locked_at,
          DROP COLUMN final_failure,
          DROP COLUMN next_attempt_at,
          DROP COLUMN deduplication_key,
          DROP COLUMN recipient_user_id,
          DROP COLUMN channel_code,
          DROP COLUMN outbox_event_id;
        """
    )
