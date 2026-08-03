"""Add analyst copilot feedback decision and reason codes."""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_analyst_feedback"
down_revision: str | None = "0018_agent_escalation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ai.feedback
          ADD COLUMN decision_code varchar(20),
          ADD COLUMN reason_code varchar(40);
        ALTER TABLE ai.feedback
          ADD CONSTRAINT ai_feedback_decision_ck CHECK (
            decision_code IS NULL
            OR decision_code IN ('APPROVED','EDITED','REJECTED')
          ),
          ADD CONSTRAINT ai_feedback_reason_ck CHECK (
            reason_code IS NULL
            OR reason_code IN (
              'INCORRECT','INCOMPLETE','NOT_RELEVANT','RISKY_ACTION',
              'POLICY_CONCERN','STYLE','OTHER'
            )
          ),
          ADD CONSTRAINT ai_feedback_rejection_reason_ck CHECK (
            decision_code IS DISTINCT FROM 'REJECTED' OR reason_code IS NOT NULL
          );
        CREATE UNIQUE INDEX feedback_analyst_acceptance_run_ux
          ON ai.feedback(agent_run_id,user_id)
          WHERE feedback_type='ANALYST_ACCEPTANCE' AND agent_run_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX ai.feedback_analyst_acceptance_run_ux;
        ALTER TABLE ai.feedback
          DROP CONSTRAINT ai_feedback_rejection_reason_ck,
          DROP CONSTRAINT ai_feedback_reason_ck,
          DROP CONSTRAINT ai_feedback_decision_ck;
        ALTER TABLE ai.feedback
          DROP COLUMN reason_code,
          DROP COLUMN decision_code;
        """
    )
