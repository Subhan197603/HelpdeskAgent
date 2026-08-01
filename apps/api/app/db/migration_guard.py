"""Static policy checks for linear and explicitly reviewed Alembic revisions."""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from apps.api.app.db.baseline_validation import BASELINE_MARKER

REVISION_PATTERN = re.compile(r"^\d{4}_[a-z0-9_]+$")
APPROVAL_PATTERN = re.compile(r"DESTRUCTIVE_MIGRATION_APPROVED:\s*(ADR-\d{4})")
DESTRUCTIVE_SQL = re.compile(
    r"\b(DROP\s+(TABLE|SCHEMA|COLUMN|CONSTRAINT|EXTENSION|TYPE)|"
    r"ALTER\s+TABLE\b.*\bALTER\s+COLUMN\b.*\b(TYPE|SET\s+NOT\s+NULL)|"
    r"ALTER\s+TABLE\b.*\bADD\s+CONSTRAINT\b.*\bFOREIGN\s+KEY\b|"
    r"ALTER\s+TYPE\b.*\bRENAME\s+(VALUE|TO)\b|"
    r"VACUUM\s+FULL|CLUSTER\s+)\b",
    re.IGNORECASE | re.DOTALL,
)
PROHIBITED_CALLS = {"drop_table", "drop_column", "drop_constraint", "drop_index"}
SCHEMA_REQUIRED_CALLS = {
    "add_column",
    "alter_column",
    "create_check_constraint",
    "create_foreign_key",
    "create_index",
    "create_table",
    "create_unique_constraint",
    "drop_column",
    "drop_constraint",
    "drop_index",
    "drop_table",
}


@dataclass(frozen=True, slots=True)
class MigrationFinding:
    path: Path
    line: int
    rule: str
    message: str


@dataclass(frozen=True, slots=True)
class RevisionInfo:
    path: Path
    revision: str
    down_revision: str | None


def _assignment(tree: ast.Module, variable: str) -> str | None:
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == variable
            and isinstance(node.value, ast.Constant)
        ):
            return node.value.value if isinstance(node.value.value, str) else None
    return None


def _call_name(node: ast.Call) -> str | None:
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
    ):
        return node.func.attr
    return None


def _has_keyword(node: ast.Call, name: str, expected: object | None = None) -> bool:
    for keyword in node.keywords:
        if keyword.arg != name:
            continue
        if expected is None:
            return True
        return isinstance(keyword.value, ast.Constant) and keyword.value.value == expected
    return False


def _valid_approval(source: str, revision: str, repository_root: Path) -> bool:
    match = APPROVAL_PATTERN.search(source)
    if match is None:
        return False
    adr_id = match.group(1)
    matches = list((repository_root / "docs/decisions").glob(f"{adr_id}-*.md"))
    return len(matches) == 1 and revision in matches[0].read_text(encoding="utf-8")


def inspect_revision(
    path: Path, repository_root: Path
) -> tuple[RevisionInfo, list[MigrationFinding]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    revision = _assignment(tree, "revision") or ""
    down_revision = _assignment(tree, "down_revision")
    info = RevisionInfo(path, revision, down_revision)
    findings: list[MigrationFinding] = []
    approved = _valid_approval(source, revision, repository_root)

    if not REVISION_PATTERN.fullmatch(revision) or len(revision) > 32:
        findings.append(MigrationFinding(path, 1, "revision-name", "Invalid stable revision ID"))
    if "install_all.sql" in source or "uninstall_all.sql" in source:
        findings.append(
            MigrationFinding(path, 1, "baseline-installer", "Baseline installers are prohibited")
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node)
        if call_name is None:
            continue
        if call_name == "execute" and (
            not node.args
            or not isinstance(node.args[0], ast.Constant)
            or not isinstance(node.args[0].value, str)
        ):
            findings.append(
                MigrationFinding(
                    path,
                    node.lineno,
                    "dynamic-sql",
                    "op.execute must use reviewable static SQL without runtime interpolation",
                )
            )
            continue
        risky_message: str | None = None
        if call_name in PROHIBITED_CALLS:
            risky_message = f"op.{call_name} is destructive"
        elif call_name == "alter_column" and (
            _has_keyword(node, "type_") or _has_keyword(node, "nullable", False)
        ):
            risky_message = "Column narrowing or non-null conversion requires a data strategy"
        elif call_name == "create_foreign_key":
            risky_message = "Foreign-key additions require size and supporting-index review"
        elif (
            call_name == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and DESTRUCTIVE_SQL.search(node.args[0].value)
        ):
            risky_message = "Raw SQL contains a destructive or rewrite-sensitive operation"
        if risky_message and not approved:
            findings.append(
                MigrationFinding(path, node.lineno, "destructive-operation", risky_message)
            )
        if call_name in SCHEMA_REQUIRED_CALLS and not (
            _has_keyword(node, "schema") or _has_keyword(node, "source_schema")
        ):
            findings.append(
                MigrationFinding(
                    path, node.lineno, "explicit-schema", f"op.{call_name} needs schema"
                )
            )
    return info, findings


def check_migrations(versions_path: Path, repository_root: Path) -> list[MigrationFinding]:
    findings: list[MigrationFinding] = []
    revisions: dict[str, RevisionInfo] = {}
    for path in sorted(versions_path.glob("*.py")):
        info, file_findings = inspect_revision(path, repository_root)
        findings.extend(file_findings)
        if info.revision in revisions:
            findings.append(MigrationFinding(path, 1, "duplicate-revision", info.revision))
        revisions[info.revision] = info

    if BASELINE_MARKER not in revisions or revisions[BASELINE_MARKER].down_revision is not None:
        findings.append(
            MigrationFinding(versions_path, 1, "baseline-root", "Baseline marker must be the root")
        )
    children: dict[str, int] = {revision: 0 for revision in revisions}
    for info in revisions.values():
        if info.down_revision is not None:
            if info.down_revision not in revisions:
                findings.append(
                    MigrationFinding(info.path, 1, "missing-parent", str(info.down_revision))
                )
            else:
                children[info.down_revision] += 1
    if any(count > 1 for count in children.values()):
        findings.append(
            MigrationFinding(versions_path, 1, "branch", "Migration history must be linear")
        )
    heads = [revision for revision, count in children.items() if count == 0]
    if len(heads) != 1:
        findings.append(MigrationFinding(versions_path, 1, "heads", "Expected exactly one head"))
    return findings
