"""Add the ticket draft aggregate and submission references."""
# ruff: noqa: E501

from collections.abc import Sequence

from alembic import op

revision: str = "0006_ticket_draft_submission"
down_revision: str | None = "0005_catalogue_form_immutability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE itsm.ticket_draft (
            draft_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
            owner_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
            requested_for_user_id uuid REFERENCES identity.app_user(user_id),
            project_id uuid NOT NULL REFERENCES config.service_project(project_id),
            service_node_id uuid REFERENCES config.service_node(service_node_id),
            request_type_id uuid NOT NULL REFERENCES config.request_type(request_type_id),
            request_type_version_id uuid NOT NULL,
            work_type_id uuid NOT NULL REFERENCES config.work_type(work_type_id),
            application_environment_id uuid REFERENCES config.application_environment(application_environment_id),
            summary varchar(500) NOT NULL DEFAULT '',
            description text,
            custom_values_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            impact_code varchar(20) REFERENCES config.impact(impact_code),
            urgency_code varchar(20) REFERENCES config.urgency(urgency_code),
            priority_code varchar(20) REFERENCES config.priority(priority_code),
            priority_matrix_id uuid REFERENCES config.priority_matrix(priority_matrix_id),
            draft_status varchar(30) NOT NULL DEFAULT 'DRAFT',
            submitted_ticket_id uuid UNIQUE REFERENCES itsm.ticket(ticket_id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
            expires_at timestamptz,
            CONSTRAINT ticket_draft_request_type_version_fk
                FOREIGN KEY (request_type_version_id, request_type_id)
                REFERENCES config.request_type_version(request_type_version_id, request_type_id),
            CONSTRAINT ticket_draft_status_ck CHECK (
                draft_status IN ('DRAFT','READY_FOR_REVIEW','SUBMITTED','EXPIRED','CANCELLED')
            ),
            CONSTRAINT ticket_draft_submission_ck CHECK (
                (draft_status = 'SUBMITTED') = (submitted_ticket_id IS NOT NULL)
            ),
            CONSTRAINT ticket_draft_expiry_ck CHECK (
                expires_at IS NULL OR expires_at > created_at
            )
        );

        CREATE INDEX ticket_draft_owner_updated_ix
            ON itsm.ticket_draft (tenant_id, owner_user_id, updated_at DESC, draft_id);
        CREATE INDEX ticket_draft_expiry_ix
            ON itsm.ticket_draft (expires_at)
            WHERE draft_status IN ('DRAFT','READY_FOR_REVIEW') AND expires_at IS NOT NULL;

        CREATE FUNCTION itsm.ticket_draft_before_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.draft_status = 'SUBMITTED' THEN
                RAISE EXCEPTION 'Submitted ticket drafts are immutable' USING ERRCODE = '55000';
            END IF;
            NEW.updated_at := clock_timestamp();
            NEW.row_version := OLD.row_version + 1;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER ticket_draft_set_version
            BEFORE UPDATE ON itsm.ticket_draft
            FOR EACH ROW EXECUTE FUNCTION itsm.ticket_draft_before_update();

        ALTER TABLE itsm.ticket
            ADD COLUMN priority_matrix_id uuid REFERENCES config.priority_matrix(priority_matrix_id);

        CREATE UNIQUE INDEX outbox_ticket_creation_event_ux
            ON integration.outbox_event (tenant_id, aggregate_type, aggregate_id, event_type)
            WHERE aggregate_type = 'TICKET'
              AND event_type IN ('ROUTE_TICKET','START_SLA','NOTIFY_TICKET_CREATED');

        -- The baseline key allocator updates the protected counter from an INSERT
        -- trigger. Execute that narrowly scoped function as its non-login owner
        -- instead of granting the runtime role arbitrary counter updates.
        ALTER FUNCTION itsm.assign_ticket_key() SECURITY DEFINER;
        ALTER FUNCTION itsm.assign_ticket_key()
            SET search_path = pg_catalog, itsm, config;

        CREATE OR REPLACE FUNCTION itsm.log_ticket_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_actor uuid := util.current_user_id();
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO itsm.ticket_event(
                    tenant_id, ticket_id, event_type, actor_type, actor_user_id,
                    event_data_json
                ) VALUES (
                    NEW.tenant_id, NEW.ticket_id, 'TICKET_CREATED',
                    CASE WHEN NEW.ai_created_flag THEN 'AI' ELSE 'USER' END,
                    COALESCE(v_actor, NEW.created_by),
                    jsonb_build_object(
                        'ticket_key', NEW.ticket_key,
                        'project_id', NEW.project_id,
                        'request_type_id', NEW.request_type_id,
                        'request_type_version_id', NEW.request_type_version_id,
                        'workflow_version_id', NEW.workflow_version_id,
                        'initial_status_id', NEW.status_id,
                        'priority_code', NEW.priority_code,
                        'source_channel', NEW.channel_code,
                        'correlation_id', current_setting('app.correlation_id', true),
                        'request_id', current_setting('app.request_id', true)
                    )
                );
                RETURN NEW;
            END IF;
            INSERT INTO itsm.ticket_event(
                tenant_id, ticket_id, event_type, actor_type, actor_user_id,
                old_values_json, new_values_json
            ) VALUES (
                NEW.tenant_id, NEW.ticket_id,
                CASE WHEN OLD.status_id IS DISTINCT FROM NEW.status_id
                     THEN 'STATUS_CHANGED' ELSE 'TICKET_UPDATED' END,
                'USER', COALESCE(v_actor, NEW.updated_by),
                jsonb_build_object('status_id', OLD.status_id, 'row_version', OLD.row_version),
                jsonb_build_object('status_id', NEW.status_id, 'row_version', NEW.row_version)
            );
            RETURN NEW;
        END;
        $$;

        CREATE POLICY tenant_isolation_ticket_draft ON itsm.ticket_draft
            USING (tenant_id = util.current_tenant_id())
            WITH CHECK (tenant_id = util.current_tenant_id());

        ALTER TABLE itsm.ticket_draft ENABLE ROW LEVEL SECURITY;

        GRANT SELECT, INSERT, UPDATE ON itsm.ticket_draft TO helpdesk_app;
        REVOKE DELETE ON itsm.ticket_draft
            FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX integration.outbox_ticket_creation_event_ux;
        ALTER FUNCTION itsm.assign_ticket_key() SECURITY INVOKER;
        ALTER FUNCTION itsm.assign_ticket_key() RESET search_path;
        CREATE OR REPLACE FUNCTION itsm.log_ticket_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_actor uuid := util.current_user_id();
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO itsm.ticket_event(
                    tenant_id, ticket_id, event_type, actor_type, actor_user_id,
                    new_values_json, event_data_json
                ) VALUES (
                    NEW.tenant_id, NEW.ticket_id, 'TICKET_CREATED',
                    CASE WHEN NEW.ai_created_flag THEN 'AI' ELSE 'USER' END,
                    COALESCE(v_actor, NEW.created_by), to_jsonb(NEW),
                    jsonb_build_object('ticket_key', NEW.ticket_key)
                );
                RETURN NEW;
            END IF;
            INSERT INTO itsm.ticket_event(
                tenant_id, ticket_id, event_type, actor_type, actor_user_id,
                old_values_json, new_values_json
            ) VALUES (
                NEW.tenant_id, NEW.ticket_id,
                CASE WHEN OLD.status_id IS DISTINCT FROM NEW.status_id
                     THEN 'STATUS_CHANGED' ELSE 'TICKET_UPDATED' END,
                'USER', COALESCE(v_actor, NEW.updated_by),
                to_jsonb(OLD), to_jsonb(NEW)
            );
            RETURN NEW;
        END;
        $$;
        ALTER TABLE itsm.ticket DROP COLUMN priority_matrix_id;
        DROP POLICY tenant_isolation_ticket_draft ON itsm.ticket_draft;
        DROP TRIGGER ticket_draft_set_version ON itsm.ticket_draft;
        DROP FUNCTION itsm.ticket_draft_before_update();
        DROP TABLE itsm.ticket_draft;
        """
    )
