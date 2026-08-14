"""Add private analyst ticket watchlists.

Watches are tenant- and owner-scoped preferences. They do not grant ticket
access or create participant, assignment, event, outbox, or notification state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_analyst_ticket_watchlist"
down_revision: str | None = "0025_analyst_canned_responses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE config.analyst_ticket_watchlist (
          watchlist_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          owner_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
          ticket_id uuid NOT NULL REFERENCES itsm.ticket(ticket_id),
          watched_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX analyst_ticket_watchlist_owner_ticket_ux "
        "ON config.analyst_ticket_watchlist (tenant_id,owner_user_id,ticket_id)"
    )
    op.execute(
        "CREATE INDEX analyst_ticket_watchlist_owner_order_ix "
        "ON config.analyst_ticket_watchlist "
        "(tenant_id,owner_user_id,watched_at DESC,watchlist_id DESC)"
    )
    op.execute("ALTER TABLE config.analyst_ticket_watchlist ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY analyst_ticket_watchlist_owner_isolation
        ON config.analyst_ticket_watchlist
        USING (
          tenant_id=util.current_tenant_id()
          AND owner_user_id=util.current_user_id()
        )
        WITH CHECK (
          tenant_id=util.current_tenant_id()
          AND owner_user_id=util.current_user_id()
        )
        """
    )
    op.execute("GRANT SELECT,INSERT,DELETE ON config.analyst_ticket_watchlist TO helpdesk_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT,INSERT,DELETE ON config.analyst_ticket_watchlist FROM helpdesk_app")
    op.execute(
        "DROP POLICY analyst_ticket_watchlist_owner_isolation ON config.analyst_ticket_watchlist"
    )
    op.drop_table("analyst_ticket_watchlist", schema="config")
