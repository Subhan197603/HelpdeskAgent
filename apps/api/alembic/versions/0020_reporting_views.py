"""Add tenant-safe OAC reporting schema and re-scope the reporting role."""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_reporting_views"
down_revision: str | None = "0019_analyst_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA reporting;

        CREATE VIEW reporting.dim_service_project AS
        SELECT tenant_id,project_id,project_key,project_name,active_flag
        FROM config.service_project;

        CREATE VIEW reporting.dim_support_group AS
        SELECT tenant_id,support_group_id,group_code,group_name,active_flag
        FROM identity.support_group;

        CREATE VIEW reporting.dim_request_type AS
        SELECT request_type.tenant_id,request_type.request_type_id,
          request_type.project_id,request_type.request_type_code,
          request_type.request_type_name,request_type.work_type_id,
          work_type.work_type_code
        FROM config.request_type request_type
        JOIN config.work_type work_type
          ON work_type.work_type_id=request_type.work_type_id;

        CREATE VIEW reporting.dim_workflow_status AS
        SELECT status_id,workflow_version_id,status_code,status_name,
          status_category,terminal_flag
        FROM config.workflow_status;

        CREATE VIEW reporting.dim_priority AS
        SELECT priority_code,priority_name,rank_order,active_flag
        FROM config.priority;

        CREATE VIEW reporting.fact_ticket AS
        SELECT ticket_id,tenant_id,project_id,ticket_number,ticket_key,
          request_type_id,work_type_id,workflow_version_id,status_id,
          impact_code,urgency_code,priority_code,
          assignment_group_id,service_node_id,category_id,
          channel_code,environment_code,resolution_code,
          ai_created_flag,
          first_response_at,resolved_at,closed_at,
          created_at,updated_at,
          updated_at AS extraction_watermark
        FROM itsm.ticket;

        CREATE VIEW reporting.fact_ticket_sla AS
        SELECT ticket_sla_id,tenant_id,ticket_id,sla_definition_id,sla_goal_id,
          state_code,started_at,target_at,paused_at,completed_at,breached_at,
          accumulated_pause_seconds,elapsed_working_seconds,
          remaining_working_seconds,last_calculated_at,
          last_calculated_at AS extraction_watermark
        FROM itsm.ticket_sla;

        CREATE VIEW reporting.fact_approval AS
        SELECT approval.ticket_approval_id,approval.tenant_id,approval.ticket_id,
          approval.approval_definition_id,approval.approval_status,
          approval.requested_at,approval.completed_at,
          count(approver.approver_user_id) AS approver_count,
          count(approver.decided_at) AS decided_count,
          coalesce(approval.completed_at,approval.requested_at)
            AS extraction_watermark
        FROM itsm.ticket_approval approval
        LEFT JOIN itsm.ticket_approver approver
          ON approver.ticket_approval_id=approval.ticket_approval_id
        GROUP BY approval.ticket_approval_id;

        CREATE VIEW reporting.fact_knowledge_document AS
        SELECT version.document_version_id,document.tenant_id,
          version.document_id,document.source_id,source.source_type,
          document.product_node_id,document.release_id,
          version.version_number,version.extraction_status,
          version.validation_status,version.current_version_flag,
          document.document_type,document.approval_status,
          document.active_flag,version.acquired_at,version.created_at,
          version.created_at AS extraction_watermark
        FROM kb.document_version version
        JOIN kb.document document ON document.document_id=version.document_id
        JOIN kb.source source ON source.source_id=document.source_id;

        CREATE VIEW reporting.fact_ai_usage AS
        SELECT usage_ledger_id,tenant_id,agent_run_id,agent_configuration_id,
          application_environment_id,provider_alias,model_alias,use_case_code,
          input_tokens,output_tokens,cached_tokens,tool_call_count,
          estimated_cost,currency_code,occurred_at,
          occurred_at AS extraction_watermark
        FROM ai.usage_ledger;

        CREATE VIEW reporting.fact_ai_feedback AS
        SELECT feedback.feedback_id,feedback.tenant_id,feedback.agent_run_id,
          feedback.feedback_type,feedback.decision_code,feedback.reason_code,
          feedback.rating_value,feedback.resolved_issue_flag,
          conversation.conversation_type,feedback.created_at,
          feedback.created_at AS extraction_watermark
        FROM ai.feedback feedback
        LEFT JOIN ai.conversation conversation
          ON conversation.conversation_id=feedback.conversation_id;

        CREATE VIEW reporting.feed_ticket_events AS
        SELECT event_id,tenant_id,ticket_id,event_type,actor_type,created_at
        FROM itsm.ticket_event;

        CREATE INDEX ticket_event_tenant_feed_ix
          ON itsm.ticket_event(tenant_id,event_id);

        REVOKE SELECT ON ALL TABLES
          IN SCHEMA identity, config, itsm, kb, ai, audit, integration
          FROM helpdesk_reporting;
        REVOKE USAGE
          ON SCHEMA util, identity, config, itsm, kb, ai, audit, integration
          FROM helpdesk_reporting;

        GRANT USAGE ON SCHEMA reporting TO helpdesk_reporting;
        GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO helpdesk_reporting;
        ALTER DEFAULT PRIVILEGES IN SCHEMA reporting
          GRANT SELECT ON TABLES TO helpdesk_reporting;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA reporting
          REVOKE SELECT ON TABLES FROM helpdesk_reporting;
        DROP SCHEMA reporting CASCADE;
        DROP INDEX itsm.ticket_event_tenant_feed_ix;

        GRANT USAGE
          ON SCHEMA util, identity, config, itsm, kb, ai, audit, integration
          TO helpdesk_reporting;
        GRANT SELECT ON ALL TABLES
          IN SCHEMA identity, config, itsm, kb, ai, audit, integration
          TO helpdesk_reporting;
        REVOKE UPDATE, DELETE ON
            itsm.assignment_history,
            itsm.ticket_event,
            itsm.ticket_sla_event,
            itsm.ticket_approval_decision,
            itsm.priority_override,
            ai.tool_call,
            ai.retrieval_evidence,
            ai.usage_ledger,
            audit.security_event,
            audit.audit_event
        FROM helpdesk_reporting;
        """
    )
