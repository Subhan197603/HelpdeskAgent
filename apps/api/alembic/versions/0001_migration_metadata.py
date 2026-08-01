"""Document ownership of the Alembic version table.

This sample post-baseline migration changes only the comment on Alembic's own version table. It
demonstrates a reversible, explicitly scoped migration without changing any domain object.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_migration_metadata"
down_revision: str | None = "0000_physical_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "COMMENT ON TABLE config.alembic_version IS "
        "'Alembic history for changes after the Fusion Helpdesk physical baseline'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON TABLE config.alembic_version IS NULL")
