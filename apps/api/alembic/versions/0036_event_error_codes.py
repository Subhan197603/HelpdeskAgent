"""Record governed error-code matching on retrieval query events.

Task 16.2 applies exact error-code candidate matching behind a per-tenant
opt-in and a global kill switch, both default off. These two nullable
observation columns record whether matching applied to a query so the
Task 16.3 analytics can measure effectiveness. Legacy rows stay NULL and
count as unmatched; grants, row-level security, and the update-immutability
trigger are unchanged.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036_event_error_codes"
down_revision: str | None = "0035_chunk_error_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.retrieval_query_event
          ADD COLUMN error_code_matching_applied boolean,
          ADD COLUMN matched_error_code_count integer CHECK (
            matched_error_code_count IS NULL OR matched_error_code_count>=0
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.retrieval_query_event
          DROP COLUMN error_code_matching_applied,
          DROP COLUMN matched_error_code_count;
        """
    )
