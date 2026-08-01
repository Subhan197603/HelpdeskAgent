"""Mark the externally installed PostgreSQL physical baseline.

This revision intentionally contains no DDL or data operations. The approved modular SQL
installer must run and be validated before this revision is stamped.
"""

from collections.abc import Sequence

revision: str = "0000_physical_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record Alembic ownership without creating or modifying baseline objects."""
    pass


def downgrade() -> None:
    """Leave the externally managed physical baseline completely intact."""
    pass
