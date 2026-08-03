"""Task 10.2 Prometheus-compatible metrics endpoint contract."""

from fastapi.testclient import TestClient

from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings


def _app(**overrides: object) -> TestClient:
    application = create_app(
        make_test_settings(**overrides),
        resource_factory=lambda _: ApplicationResources(
            FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe()
        ),
    )
    return TestClient(application)


def test_metrics_endpoint_exposes_prometheus_counters_without_sensitive_data() -> None:
    with _app() as client:
        client.app.state.ticket_metrics.tickets_submitted = 3  # type: ignore[attr-defined]
        client.app.state.copilot_metrics.drafts_created = 2  # type: ignore[attr-defined]
        client.app.state.copilot_metrics.record_feedback("REJECTED")  # type: ignore[attr-defined]
        response = client.get("/api/v1/observability/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "helpdesk_tickets_submitted_total 3" in body
    assert "helpdesk_copilot_drafts_created_total 2" in body
    assert 'helpdesk_copilot_feedback_total{decision="REJECTED"} 1' in body
    assert "helpdesk_copilot_provider_failures_total 0" in body
    assert "# TYPE helpdesk_tickets_submitted_total counter" in body
    assert "password" not in body.lower()
    assert "@" not in body


def test_metrics_endpoint_can_be_disabled() -> None:
    with _app(metrics_endpoint_enabled=False) as client:
        response = client.get("/api/v1/observability/metrics")
    assert response.status_code == 404
