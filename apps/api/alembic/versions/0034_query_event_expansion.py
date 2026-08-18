"""Record synonym-expansion evidence on retrieval query events.

Task 15.2 applies approved synonym expansions inside the shared retrieval
service, per-tenant opt-in and default off. The two nullable columns are
additive, backward-compatible observation only: legacy rows stay NULL, and
new rows record whether expansion applied and how many approved expansions
were appended. Grants, row-level security, and the update-immutability
trigger are unchanged.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034_query_event_expansion"
down_revision: str | None = "0033_retrieval_synonyms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.retrieval_query_event
          ADD COLUMN expansion_applied boolean,
          ADD COLUMN expanded_term_count integer CHECK (
            expanded_term_count IS NULL OR expanded_term_count>=0
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.retrieval_query_event
          DROP COLUMN expansion_applied,
          DROP COLUMN expanded_term_count;
        """
    )
