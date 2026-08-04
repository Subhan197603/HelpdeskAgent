"""Task 10.3 backup, recovery-runbook, and production-readiness policy checks."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKUP_DOC = ROOT / "docs/operations/backup-disaster-recovery.md"
RUNBOOKS_DOC = ROOT / "docs/operations/runbooks.md"
READINESS_DOC = ROOT / "docs/operations/production-readiness.md"
BACKUP_SCRIPT = ROOT / "infrastructure/backup/backup_database.sh"
RESTORE_SCRIPT = ROOT / "infrastructure/backup/restore_database.sh"
REQUIRED_RUNBOOKS = (
    "Deployment",
    "Rollback",
    "Database migration",
    "Incident response",
    "Security incident",
    "AI disable",
    "AI provider outage",
)
REQUIRED_SIGNOFF_ROLES = (
    "Architecture",
    "Security",
    "Data",
    "Operations",
    "Support",
    "Business",
)


def test_backup_doc_covers_strategy_pitr_storage_secrets_and_recovery_objectives() -> None:
    document = BACKUP_DOC.read_text(encoding="utf-8")
    for section in (
        "## Backup strategy",
        "## Point-in-time recovery",
        "## Object storage protection and recovery",
        "## Secrets and configuration recovery",
        "## Restore procedure",
        "## Disaster recovery exercise",
        "## Recovery objectives",
    ):
        assert section in document, section
    assert re.search(r"RPO[^\n]*\d+\s*(minute|hour)", document), "RPO target missing"
    assert re.search(r"RTO[^\n]*\d+\s*(minute|hour)", document), "RTO target missing"
    assert "wal_level" in document, "PITR plan must state WAL prerequisites"


def test_backup_and_restore_automation_scripts_exist() -> None:
    backup = BACKUP_SCRIPT.read_text(encoding="utf-8")
    restore = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in backup and "set -euo pipefail" in restore
    assert "pg_dump" in backup, "backup script must use pg_dump"
    assert "pg_restore" in restore, "restore script must use pg_restore"


def test_required_operational_runbooks_exist_with_trigger_steps_verification() -> None:
    document = RUNBOOKS_DOC.read_text(encoding="utf-8")
    for name in REQUIRED_RUNBOOKS:
        heading = f"## Runbook: {name}"
        assert heading in document, heading
        _, _, body = document.partition(heading)
        body = body.split("## Runbook:", 1)[0]
        for part in ("### Trigger", "### Steps", "### Verification"):
            assert part in body, f"{name} missing {part}"


def test_ai_disable_runbook_references_real_kill_switch() -> None:
    document = RUNBOOKS_DOC.read_text(encoding="utf-8")
    assert "AI_GLOBALLY_ENABLED" in document
    assert "backup-disaster-recovery.md" in document


def test_readiness_checklist_is_complete_and_signed_off() -> None:
    document = READINESS_DOC.read_text(encoding="utf-8")
    assert "- [ ]" not in document, "readiness checklist has unchecked items"
    assert document.count("- [x]") >= 10
    for role in REQUIRED_SIGNOFF_ROLES:
        row = re.search(rf"\|\s*{role}\s*\|[^\n|]+\|[^\n|]*2026-\d\d-\d\d", document)
        assert row, f"missing dated sign-off for {role}"


def test_readiness_records_risks_with_owner_and_acceptance_and_release_candidate() -> None:
    document = READINESS_DOC.read_text(encoding="utf-8")
    assert "## Unresolved risks" in document
    risks = document.split("## Unresolved risks", 1)[1]
    assert "Owner" in risks and "Acceptance" in risks
    assert "v1.0.0-rc.1" in document, "release candidate tag plan missing"
    assert "## Deferred backlog" in document
