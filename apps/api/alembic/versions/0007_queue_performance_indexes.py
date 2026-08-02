"""Add stable analyst-queue and safe ticket-search indexes."""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_queue_performance_indexes"
down_revision: str | None = "0006_ticket_draft_submission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ticket_queue_unassigned_created_ix
            ON itsm.ticket (tenant_id, created_at DESC, ticket_id DESC)
            WHERE assignment_group_id IS NULL;
        CREATE INDEX ticket_queue_assignee_created_ix
            ON itsm.ticket (
                tenant_id, assignee_user_id, created_at DESC, ticket_id DESC
            );
        CREATE INDEX ticket_queue_group_created_ix
            ON itsm.ticket (
                tenant_id, assignment_group_id, created_at DESC, ticket_id DESC
            );
        CREATE INDEX ticket_queue_project_created_ix
            ON itsm.ticket (tenant_id, project_id, created_at DESC, ticket_id DESC);
        CREATE INDEX ticket_queue_search_ix
            ON itsm.ticket USING gin (
                to_tsvector('simple', coalesce(ticket_key, '') || ' ' || summary)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX itsm.ticket_queue_search_ix;
        DROP INDEX itsm.ticket_queue_project_created_ix;
        DROP INDEX itsm.ticket_queue_group_created_ix;
        DROP INDEX itsm.ticket_queue_assignee_created_ix;
        DROP INDEX itsm.ticket_queue_unassigned_created_ix;
        """
    )
