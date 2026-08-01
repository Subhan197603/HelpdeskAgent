"""Application factory, health, middleware, and error tests."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.core.exceptions import ConflictError
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings


def test_application_factory_exposes_openapi_and_secure_headers(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    test_app = client.app
    assert isinstance(test_app, FastAPI)
    assert response.json()["info"]["title"] == test_app.state.settings.app_name
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_liveness_does_not_call_dependencies() -> None:
    resources = ApplicationResources(
        FakeProbe(False), FakeProbe(False), FakeProbe(False), FakeProbe(False)
    )
    with TestClient(
        create_app(make_test_settings(), resource_factory=lambda _: resources)
    ) as test_client:
        response = test_client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["dependencies"] == {}


@pytest.mark.parametrize("failed_dependency", ["database", "redis"])
def test_readiness_fails_for_required_dependency(failed_dependency: str) -> None:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe(False))
    setattr(resources, failed_dependency, FakeProbe(False))
    with TestClient(
        create_app(make_test_settings(), resource_factory=lambda _: resources)
    ) as test_client:
        response = test_client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert "localhost" not in response.text


def test_readiness_and_versioned_health_report_dependencies(client: TestClient) -> None:
    for path in ("/health/ready", "/api/v1/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        assert set(response.json()["dependencies"]) == {
            "postgresql",
            "redis",
            "object_storage",
            "clamav",
        }


def test_correlation_id_is_generated_and_propagated(client: TestClient) -> None:
    response = client.get("/health/live")
    assert UUID(response.headers["x-correlation-id"])
    assert response.json()["correlation_id"] == response.headers["x-correlation-id"]


def test_valid_correlation_id_is_accepted(client: TestClient) -> None:
    correlation_id = str(uuid4())
    response = client.get("/health/live", headers={"X-Correlation-ID": correlation_id})
    assert response.headers["x-correlation-id"] == correlation_id


def test_invalid_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "not valid!"})
    assert response.headers["x-correlation-id"] != "not valid!"
    assert UUID(response.headers["x-correlation-id"])


@pytest.mark.anyio
async def test_correlation_context_is_isolated_between_concurrent_requests() -> None:
    app = create_app(
        make_test_settings(),
        resource_factory=lambda _: ApplicationResources(
            FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe()
        ),
    )
    ids = [str(uuid4()) for _ in range(20)]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *(client.get("/health/live", headers={"X-Correlation-ID": item}) for item in ids)
        )
    assert [response.json()["correlation_id"] for response in responses] == ids


def test_problem_response_contains_safe_standard_fields() -> None:
    app: FastAPI = create_app(
        make_test_settings(),
        resource_factory=lambda _: ApplicationResources(
            FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe()
        ),
    )

    @app.get("/test-conflict")
    async def conflict() -> None:
        raise ConflictError("The submitted resource conflicts with current state.")

    with TestClient(app) as test_client:
        response = test_client.get("/test-conflict")
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "https://helpdesk.example/problems/conflict",
        "title": "Conflict",
        "status": 409,
        "detail": "The submitted resource conflicts with current state.",
        "instance": "/test-conflict",
        "correlation_id": response.headers["x-correlation-id"],
    }


def test_resources_close_on_shutdown(fake_resources: ApplicationResources) -> None:
    app = create_app(make_test_settings(), resource_factory=lambda _: fake_resources)
    with TestClient(app):
        pass
    probes = (
        fake_resources.database,
        fake_resources.redis,
        fake_resources.object_storage,
        fake_resources.clamav,
    )
    assert all(isinstance(probe, FakeProbe) and probe.closed for probe in probes)
