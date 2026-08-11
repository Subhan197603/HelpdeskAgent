"""Grant the API runtime role the single write needed for catalogue visibility.

Task 11.5C ships read-only workflow/SLA/calendar/catalogue administration plus
one safe mutation: toggling a request type's portal visibility. The physical
baseline grants ``helpdesk_app`` SELECT-only access to every ``config`` table,
so the mutation fails closed without this grant. The grant is column-scoped to
exactly the two flags the endpoint may change; the ``updated_at`` concurrency
token is maintained by the table's trigger running as the table owner. No other
configuration write is granted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_admin_config_privileges"
down_revision: str | None = "0021_admin_access_privileges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "GRANT UPDATE (active_flag, employee_visible_flag) ON config.request_type TO helpdesk_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (active_flag, employee_visible_flag) "
        "ON config.request_type FROM helpdesk_app"
    )
