"""Permit non-owner runtime roles to evaluate optional RLS policies."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_rls_runtime_privileges"
down_revision: str | None = "0002_identity_role_activation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "GRANT EXECUTE ON FUNCTION util.current_tenant_id(), util.current_user_id() "
        "TO helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE EXECUTE ON FUNCTION util.current_tenant_id(), util.current_user_id() "
        "FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly"
    )
