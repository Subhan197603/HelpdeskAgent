"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

Migration review requirements:
- Use explicit schema, constraint, and index names.
- Explain lock-sensitive operations.
- Add downgrade logic unless its omission is explicitly justified.
- Approved destructive work requires: DESTRUCTIVE_MIGRATION_APPROVED: ADR-NNNN
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Apply the reviewed forward migration."""
    pass


def downgrade() -> None:
    """Reverse the migration, or document why reversal is impossible."""
    pass
