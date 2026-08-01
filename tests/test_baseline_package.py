import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "database" / "baseline" / "fusion_helpdesk_postgres"


def test_baseline_package_is_complete() -> None:
    expected_paths = {
        BASELINE / "README.md",
        BASELINE / "manifest",
        BASELINE / "scripts",
        BASELINE / "sql" / "install_all.sql",
        BASELINE / "sql" / "uninstall_all.sql",
    }

    assert all(path.exists() for path in expected_paths)


def test_baseline_checksums_match() -> None:
    entries = (BASELINE / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()

    for entry in entries:
        expected_hash, relative_path = entry.split("  ./", maxsplit=1)
        content = (BASELINE / relative_path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_hash
