"""Add concurrency-safe employee-agent turns and API runtime privileges."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0022

from collections.abc import Sequence

from alembic import op

revision: str = "0017_employee_agent"
down_revision: str | None = "0016_retrieval_fusion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai.conversation_turn (
          conversation_turn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          conversation_id uuid NOT NULL REFERENCES ai.conversation(conversation_id)
            ON DELETE CASCADE,
          user_message_id uuid NOT NULL REFERENCES ai.message(message_id),
          assistant_message_id uuid REFERENCES ai.message(message_id),
          agent_run_id uuid REFERENCES ai.agent_run(agent_run_id),
          state_code varchar(50) NOT NULL,
          turn_status varchar(20) NOT NULL DEFAULT 'ACTIVE',
          outcome_code varchar(40),
          retrieval_configuration_version_id uuid
            REFERENCES ai.retrieval_configuration_version(retrieval_configuration_version_id),
          cancellation_requested_at timestamptz,
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          safe_failure_code varchar(100),
          CONSTRAINT conversation_turn_state_ck CHECK (state_code IN (
            'NEW','COLLECTING_INFORMATION','CLASSIFIED','SEARCHING_KNOWLEDGE',
            'SOLUTION_PROPOSED','AWAITING_RESOLUTION_CONFIRMATION',
            'RESOLVED_WITHOUT_TICKET','COLLECTING_TICKET_FIELDS','TICKET_DRAFT_READY',
            'AWAITING_USER_CONFIRMATION','TICKET_SUBMITTED'
          )),
          CONSTRAINT conversation_turn_status_ck CHECK (
            turn_status IN ('ACTIVE','COMPLETED','CANCELLED','FAILED')
          ),
          CONSTRAINT conversation_turn_outcome_ck CHECK (outcome_code IS NULL OR outcome_code IN (
            'RESOLUTION_PROPOSED','ESCALATION_RECOMMENDED','SAFE_REFUSAL','AI_UNAVAILABLE'
          )),
          CONSTRAINT conversation_turn_completion_ck CHECK (
            (turn_status = 'ACTIVE' AND completed_at IS NULL)
            OR (turn_status <> 'ACTIVE' AND completed_at IS NOT NULL)
          )
        );

        CREATE UNIQUE INDEX conversation_one_active_turn_ux
          ON ai.conversation_turn(conversation_id) WHERE turn_status = 'ACTIVE';
        CREATE INDEX conversation_turn_history_ix
          ON ai.conversation_turn(tenant_id,conversation_id,started_at DESC);
        CREATE INDEX conversation_message_history_ix
          ON ai.message(conversation_id,created_at DESC,message_id DESC);

        CREATE POLICY tenant_isolation_conversation_turn ON ai.conversation_turn
          USING (tenant_id = util.current_tenant_id())
          WITH CHECK (tenant_id = util.current_tenant_id());

        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'ai' AND c.relname = 'conversation'
              AND c.relrowsecurity
          ) THEN
            ALTER TABLE ai.conversation_turn ENABLE ROW LEVEL SECURITY;
          END IF;
        END
        $$;

        GRANT INSERT, UPDATE ON ai.conversation, ai.agent_run
          TO helpdesk_app;
        GRANT INSERT ON ai.message TO helpdesk_app;
        GRANT INSERT ON ai.tool_call, ai.retrieval_evidence, ai.usage_ledger
          TO helpdesk_app;
        GRANT SELECT, INSERT, UPDATE ON ai.conversation_turn
          TO helpdesk_app, helpdesk_worker;
        REVOKE DELETE ON ai.conversation_turn
          FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE INSERT, UPDATE ON ai.conversation, ai.agent_run
          FROM helpdesk_app;
        REVOKE INSERT ON ai.message FROM helpdesk_app;
        REVOKE INSERT ON ai.tool_call, ai.retrieval_evidence, ai.usage_ledger
          FROM helpdesk_app;
        DROP POLICY IF EXISTS tenant_isolation_conversation_turn ON ai.conversation_turn;
        DROP INDEX IF EXISTS ai.conversation_message_history_ix;
        DROP TABLE ai.conversation_turn;
        """
    )
