"""Add explicit role and assignment activation state.

The physical baseline effective-dates user-role rows but cannot represent an inactive role
definition or suspend an assignment without changing its validity window. Task 2.1 requires both
inactive states to fail closed, so this reviewed post-baseline migration adds only those flags.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity_role_activation"
down_revision: str | None = "0001_migration_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "role_definition",
        sa.Column("active_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="identity",
    )
    op.add_column(
        "user_role",
        sa.Column("active_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_column("user_role", "active_flag", schema="identity")
    op.drop_column("role_definition", "active_flag", schema="identity")
