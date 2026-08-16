"""Add approved-source refresh lifecycle metadata.

Refresh lifecycle columns record administrative refresh intent for governed
knowledge sources. They never trigger acquisition, never change retrieval
eligibility, and never alter source approval state. The reserved REFRESHING
value is set only by the later pipeline integration task; Task 13.1 admin
transitions use CURRENT, REFRESH_DUE, and STALE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_knowledge_source_lifecycle"
down_revision: str | None = "0026_analyst_ticket_watchlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.source
          ADD COLUMN refresh_state varchar(16) NOT NULL DEFAULT 'CURRENT',
          ADD COLUMN refresh_due_at timestamptz,
          ADD COLUMN last_refresh_requested_at timestamptz,
          ADD COLUMN last_refresh_requested_by uuid REFERENCES identity.app_user(user_id),
          ADD COLUMN last_refresh_completed_at timestamptz,
          ADD CONSTRAINT kb_source_refresh_state_ck CHECK (
            refresh_state IN ('CURRENT','REFRESH_DUE','REFRESHING','STALE')
          )
        """
    )
    op.execute(
        "CREATE INDEX kb_source_refresh_lifecycle_ix "
        "ON kb.source (tenant_id,refresh_state,refresh_due_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX kb.kb_source_refresh_lifecycle_ix")
    op.execute(
        """
        ALTER TABLE kb.source
          DROP CONSTRAINT kb_source_refresh_state_ck,
          DROP COLUMN refresh_state,
          DROP COLUMN refresh_due_at,
          DROP COLUMN last_refresh_requested_at,
          DROP COLUMN last_refresh_requested_by,
          DROP COLUMN last_refresh_completed_at
        """
    )
