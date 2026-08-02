"""Add retry-safe attachment lifecycle constraints and indexes."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_attachment_lifecycle"
down_revision: str | None = "0007_queue_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE itsm.ticket_attachment
          ADD COLUMN scan_attempt_count integer NOT NULL DEFAULT 0,
          ADD COLUMN next_scan_at timestamptz,
          ADD CONSTRAINT attachment_scan_attempt_ck CHECK (scan_attempt_count BETWEEN 0 AND 10),
          ADD CONSTRAINT attachment_scan_metadata_ck CHECK (
            malware_scan_status NOT IN ('CLEAN','INFECTED') OR
            (malware_scanned_at IS NOT NULL AND scanner_engine IS NOT NULL
             AND scanner_version IS NOT NULL)
          ),
          ADD CONSTRAINT attachment_rejection_ck CHECK (
            quarantine_status <> 'REJECTED' OR
            (malware_scan_status IN ('INFECTED','ERROR') AND rejected_at IS NOT NULL)
          );
        CREATE INDEX ticket_attachment_ticket_created_ix
          ON itsm.ticket_attachment(ticket_id, created_at, attachment_id);
        CREATE INDEX ticket_attachment_checksum_ix
          ON itsm.ticket_attachment(sha256_checksum);
        CREATE INDEX ticket_attachment_scan_retry_ix
          ON itsm.ticket_attachment(next_scan_at, attachment_id)
          WHERE malware_scan_status = 'ERROR' AND quarantine_status = 'QUARANTINED';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX itsm.ticket_attachment_scan_retry_ix;
        DROP INDEX itsm.ticket_attachment_checksum_ix;
        DROP INDEX itsm.ticket_attachment_ticket_created_ix;
        ALTER TABLE itsm.ticket_attachment
          DROP CONSTRAINT attachment_rejection_ck,
          DROP CONSTRAINT attachment_scan_metadata_ck,
          DROP CONSTRAINT attachment_scan_attempt_ck,
          DROP COLUMN next_scan_at,
          DROP COLUMN scan_attempt_count;
        """
    )
