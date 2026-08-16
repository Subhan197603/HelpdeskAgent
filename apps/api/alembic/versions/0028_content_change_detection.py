"""Add per-page content-change evidence for approved-source refresh runs.

Refresh runs re-acquire only already-approved sources and classify each page
as unchanged, changed, removed, or redirected using content hashing. The
classification columns are evidence only: they never publish content, never
change retrieval eligibility, and stay NULL for ordinary acquisition runs.
The expanded item statuses record remote removals and redirects as terminal,
non-failure outcomes.
"""

# DESTRUCTIVE_MIGRATION_APPROVED: ADR-0030

from collections.abc import Sequence

from alembic import op

revision: str = "0028_content_change_detection"
down_revision: str | None = "0027_knowledge_source_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE kb.ingestion_run
          DROP CONSTRAINT ingestion_run_type_ck,
          ADD CONSTRAINT ingestion_run_type_ck CHECK (
            run_type IN ('ACQUISITION','EXTRACTION','CHUNKING','EMBEDDING',
              'VALIDATION','FULL_PIPELINE','REFRESH')
          );

        ALTER TABLE kb.ingestion_run_item
          ADD COLUMN change_classification varchar(16),
          ADD COLUMN previous_sha256 varchar(64),
          ADD COLUMN redirect_target_url text,
          ADD COLUMN observed_http_status integer,
          ADD CONSTRAINT ingestion_item_change_classification_ck CHECK (
            change_classification IS NULL OR change_classification IN (
              'UNCHANGED','CHANGED','REMOVED','REDIRECTED'
            )
          ),
          ADD CONSTRAINT ingestion_item_previous_sha256_ck CHECK (
            previous_sha256 IS NULL OR previous_sha256 ~ '^[0-9a-f]{64}$'
          ),
          ADD CONSTRAINT ingestion_item_http_status_ck CHECK (
            observed_http_status IS NULL
            OR (observed_http_status BETWEEN 100 AND 599)
          ),
          DROP CONSTRAINT ingestion_item_status_ck,
          ADD CONSTRAINT ingestion_item_status_ck CHECK (
            item_status IN (
              'AWAITING_UPLOAD','QUEUED','ACQUIRING','ACQUIRED','EXTRACTING','EXTRACTED',
              'CHUNKING','CHUNKED','EMBEDDING','EMBEDDED','VALIDATING','PUBLISHED',
              'SKIPPED_UNCHANGED','SKIPPED_REMOVED','SKIPPED_REDIRECTED',
              'BLOCKED_PERMISSION','FAILED'
            )
          );

        GRANT UPDATE (refresh_state,refresh_due_at,last_refresh_completed_at)
          ON kb.source TO helpdesk_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE UPDATE (refresh_state,refresh_due_at,last_refresh_completed_at)
          ON kb.source FROM helpdesk_worker;

        ALTER TABLE kb.ingestion_run_item
          DROP CONSTRAINT ingestion_item_status_ck,
          ADD CONSTRAINT ingestion_item_status_ck CHECK (
            item_status IN (
              'AWAITING_UPLOAD','QUEUED','ACQUIRING','ACQUIRED','EXTRACTING','EXTRACTED',
              'CHUNKING','CHUNKED','EMBEDDING','EMBEDDED','VALIDATING','PUBLISHED',
              'SKIPPED_UNCHANGED','BLOCKED_PERMISSION','FAILED'
            )
          ),
          DROP CONSTRAINT ingestion_item_http_status_ck,
          DROP CONSTRAINT ingestion_item_previous_sha256_ck,
          DROP CONSTRAINT ingestion_item_change_classification_ck,
          DROP COLUMN observed_http_status,
          DROP COLUMN redirect_target_url,
          DROP COLUMN previous_sha256,
          DROP COLUMN change_classification;

        ALTER TABLE kb.ingestion_run
          DROP CONSTRAINT ingestion_run_type_ck,
          ADD CONSTRAINT ingestion_run_type_ck CHECK (
            run_type IN ('ACQUISITION','EXTRACTION','CHUNKING','EMBEDDING',
              'VALIDATION','FULL_PIPELINE')
          );
        """
    )
