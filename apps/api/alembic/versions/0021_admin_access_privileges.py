"""Grant the API runtime role the minimal writes for access administration.

Task 11.5F introduces user activation, role assignment, and queue-membership
mutations. The physical baseline grants ``helpdesk_app`` read-only access to
these identity tables, so the service failed closed with ``permission denied``.
Grants stay column-scoped where PostgreSQL supports it: user status flips only
``active_flag`` (the ``updated_at`` trigger fires as the table owner), role
removal closes only ``active_flag``/``valid_to``, and membership changes touch
only ``active_flag``/``member_role``. No broader identity writes are granted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_admin_access_privileges"
down_revision: str | None = "0020_reporting_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (active_flag) ON identity.app_user TO helpdesk_app")
    op.execute(
        "GRANT INSERT (tenant_id, user_id, role_code, granted_by) "
        "ON identity.user_role TO helpdesk_app"
    )
    op.execute("GRANT UPDATE (active_flag, valid_to) ON identity.user_role TO helpdesk_app")
    op.execute(
        "GRANT INSERT (support_group_id, user_id, member_role) "
        "ON identity.support_group_member TO helpdesk_app"
    )
    op.execute(
        "GRANT UPDATE (active_flag, member_role) ON identity.support_group_member TO helpdesk_app"
    )


def downgrade() -> None:
    op.execute("REVOKE UPDATE (active_flag) ON identity.app_user FROM helpdesk_app")
    op.execute("REVOKE INSERT ON identity.user_role FROM helpdesk_app")
    op.execute("REVOKE UPDATE (active_flag, valid_to) ON identity.user_role FROM helpdesk_app")
    op.execute("REVOKE INSERT ON identity.support_group_member FROM helpdesk_app")
    op.execute(
        "REVOKE UPDATE (active_flag, member_role) "
        "ON identity.support_group_member FROM helpdesk_app"
    )
