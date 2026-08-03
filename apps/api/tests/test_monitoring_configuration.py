"""Task 10.2 alert-rule and SLO configuration policy checks."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
ALERTS = ROOT / "infrastructure/monitoring/prometheus-alerts.yml"
MONITORING_DOC = ROOT / "docs/operations/monitoring.md"
REQUIRED_ALERTS = {
    "APIHighErrorRate",
    "APIHighLatencyP95",
    "SLAWorkerLag",
    "AIProviderFailureRate",
    "AIBudgetNearHardStop",
    "DBPoolSaturation",
    "OutboxBacklog",
}


def _alerts() -> list[dict[str, object]]:
    payload = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    return [rule for group in payload["groups"] for rule in group["rules"] if "alert" in rule]


def test_required_alerts_exist_with_expressions_severity_and_runbooks() -> None:
    rules = _alerts()
    names = {str(rule["alert"]) for rule in rules}
    assert names >= REQUIRED_ALERTS
    for rule in rules:
        labels = rule.get("labels")
        annotations = rule.get("annotations")
        assert isinstance(labels, dict) and isinstance(annotations, dict), rule["alert"]
        assert str(rule.get("expr", "")).strip(), rule["alert"]
        assert labels.get("severity") in {"critical", "warning"}, rule["alert"]
        assert str(annotations.get("summary", "")).strip(), rule["alert"]
        runbook = str(annotations.get("runbook_url", ""))
        assert "docs/operations/monitoring.md#" in runbook, rule["alert"]


def test_critical_alerts_are_configured() -> None:
    critical = [rule for rule in _alerts() if rule["labels"]["severity"] == "critical"]  # type: ignore[index]
    assert {str(rule["alert"]) for rule in critical} >= {
        "APIHighErrorRate",
        "AIBudgetNearHardStop",
        "DBPoolSaturation",
    }


def test_alert_runbook_anchors_exist_in_monitoring_doc() -> None:
    document = MONITORING_DOC.read_text(encoding="utf-8").lower()
    for rule in _alerts():
        annotations = rule["annotations"]
        assert isinstance(annotations, dict)
        anchor = str(annotations["runbook_url"]).split("#", 1)[1]
        assert f"## runbook: {anchor.replace('-', ' ')}" in document, anchor


def test_monitoring_doc_defines_slos_and_ai_thresholds() -> None:
    document = MONITORING_DOC.read_text(encoding="utf-8")
    for required in (
        "## Service level objectives",
        "availability",
        "p95",
        "citation coverage",
        "unsupported-answer",
        "hallucinated citation",
    ):
        assert required.lower() in document.lower(), required
