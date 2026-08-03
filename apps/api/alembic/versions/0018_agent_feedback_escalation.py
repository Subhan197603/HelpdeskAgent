"""Link employee conversations to reviewed drafts and submitted tickets."""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0023

from collections.abc import Sequence

from alembic import op

revision: str = "0018_agent_escalation"
down_revision: str | None = "0017_employee_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE itsm.ticket_draft
          ADD COLUMN source_conversation_id uuid
            REFERENCES ai.conversation(conversation_id);
        CREATE UNIQUE INDEX ticket_draft_source_conversation_ux
          ON itsm.ticket_draft(source_conversation_id)
          WHERE source_conversation_id IS NOT NULL;

        CREATE UNIQUE INDEX feedback_resolution_outcome_ux
          ON ai.feedback(conversation_id,user_id,feedback_type)
          WHERE feedback_type='RESOLUTION_OUTCOME';

        GRANT SELECT, INSERT ON ai.feedback TO helpdesk_app;
        REVOKE UPDATE, DELETE ON ai.feedback
          FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE SELECT, INSERT ON ai.feedback FROM helpdesk_app;
        DROP INDEX ai.feedback_resolution_outcome_ux;
        DROP INDEX itsm.ticket_draft_source_conversation_ux;
        ALTER TABLE itsm.ticket_draft DROP COLUMN source_conversation_id;
        """
    )
