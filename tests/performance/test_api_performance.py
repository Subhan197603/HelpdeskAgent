"""Task 10.2 load, concurrency, and pool-sizing validation against PostgreSQL."""

import asyncio
import os
import statistics
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-performance-test"
PORT = "55460"
DATABASE = "performance_model"
CUSTOMER = {"X-Developer-User": "DEV/customer"}
AGENT = {"X-Developer-User": "DEV/agent"}
P95_BUDGET_SECONDS = 0.75
SUBMISSION_BATCH = 12
LOAD_REQUESTS = 40


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and result.returncode:
        pytest.fail(result.stdout + result.stderr)
    return result


def _psql(sql: str) -> str:
    return _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        DATABASE,
        "-Atqc",
        sql,
    ).stdout.strip()


def _migrate(*arguments: str) -> None:
    environment = _environment()
    environment["MIGRATION_DATABASE_URL"] = (
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
    )
    result = subprocess.run(
        ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", *arguments],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module", autouse=True)
def performance_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            command = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                command += ["-v", "app_password=helpdesk"]
            _compose(*command, "-U", "postgres", "-d", DATABASE, "-f", file)
        _migrate("stamp")
        _migrate("upgrade")
        for file in ("/development/identity_personas.sql", "/development/catalogue.sql"):
            _compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                DATABASE,
                "-f",
                file,
            )
        _psql(
            """
            INSERT INTO itsm.ticket(
              tenant_id,project_id,request_type_id,request_type_version_id,work_type_id,
              workflow_version_id,status_id,summary,reporter_user_id,priority_code,
              channel_code,created_by,updated_by)
            SELECT '20000000-0000-0000-0000-000000000001',request_type.project_id,
              request_type.request_type_id,request_version.request_type_version_id,
              request_type.work_type_id,'32100000-0000-0000-0000-000000000001',
              '32200000-0000-0000-0000-000000000002',
              'Seed backlog ticket ' || series,
              '22000000-0000-0000-0000-000000000005','P3','PORTAL',
              '22000000-0000-0000-0000-000000000005','22000000-0000-0000-0000-000000000005'
            FROM generate_series(1,300) series
            JOIN config.request_type request_type
              ON request_type.request_type_id='33000000-0000-0000-0000-000000000001'
            JOIN config.request_type_version request_version
              ON request_version.request_type_id=request_type.request_type_id
             AND request_version.version_status='PUBLISHED';
            """
        )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}",
        "redis_url": "redis://localhost:6379/15",
        "trusted_hosts": ["testserver"],
        "developer_identity_enabled": True,
    }
    values.update(overrides)
    return Settings.model_validate(values)


class _HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(
        Database(settings), _HealthyProbe(), _HealthyProbe(), _HealthyProbe()
    )


async def _timed_get(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> tuple[int, float]:
    started = time.perf_counter()
    response = await client.get(url, headers=headers)
    return response.status_code, time.perf_counter() - started


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[18]


def _run(app: Any, coroutine: Any) -> Any:
    async def wrapped() -> Any:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await coroutine(client)

    return asyncio.run(wrapped(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.integration
def test_api_load_meets_latency_budget_under_concurrency() -> None:
    from fastapi.testclient import TestClient

    app = create_app(_settings(), resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as warm:
        assert warm.get("/api/v1/catalog/projects", headers=CUSTOMER).status_code == 200
        assert warm.get("/api/v1/agent/queues", headers=AGENT).status_code == 200

        async def load(client: httpx.AsyncClient) -> list[tuple[int, float]]:
            catalogue = [
                _timed_get(client, "/api/v1/catalog/projects", CUSTOMER)
                for _ in range(LOAD_REQUESTS // 2)
            ]
            queues = [
                _timed_get(client, "/api/v1/agent/queues", AGENT) for _ in range(LOAD_REQUESTS // 2)
            ]
            return await asyncio.gather(*catalogue, *queues)

        results = _run(app, load)
    statuses = [status for status, _ in results]
    durations = [duration for _, duration in results]
    assert statuses == [200] * LOAD_REQUESTS
    assert _p95(durations) < P95_BUDGET_SECONDS, f"p95={_p95(durations):.3f}s"


@pytest.mark.integration
def test_concurrent_ticket_submissions_stay_unique_and_idempotent() -> None:
    from fastapi.testclient import TestClient

    app = create_app(_settings(), resource_factory=_resources)
    before = int(_psql("SELECT count(*) FROM itsm.ticket"))
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        drafts: list[dict[str, Any]] = []
        for index in range(SUBMISSION_BATCH + 1):
            created = client.post(
                "/api/v1/ticket-drafts",
                headers=CUSTOMER,
                json={
                    "request_type_id": "33000000-0000-0000-0000-000000000001",
                    "summary": f"Performance submission {index}",
                    "description": "Concurrent submission validation.",
                    "impact": "LIMITED",
                    "urgency": "NORMAL",
                    "custom_fields": [{"field_code": "environment", "value": "PROD"}],
                },
            )
            assert created.status_code == 201, created.text
            draft = created.json()
            validated = client.post(
                f"/api/v1/ticket-drafts/{draft['id']}/validate",
                headers=CUSTOMER,
                json={"row_version": draft["row_version"]},
            )
            assert validated.status_code == 200, validated.text
            drafts.append(validated.json()["draft"])

        async def submit_all(client_async: httpx.AsyncClient) -> list[httpx.Response]:
            unique = [
                client_async.post(
                    f"/api/v1/ticket-drafts/{draft['id']}/submit",
                    headers={**CUSTOMER, "Idempotency-Key": f"perf-{draft['id']}"},
                    json={"row_version": draft["row_version"]},
                )
                for draft in drafts[:SUBMISSION_BATCH]
            ]
            return await asyncio.gather(*unique)

        started = time.perf_counter()
        submissions = _run(app, submit_all)
        elapsed = time.perf_counter() - started

        duplicate = drafts[SUBMISSION_BATCH]

        async def duplicate_storm(client_async: httpx.AsyncClient) -> list[httpx.Response]:
            same_key = [
                client_async.post(
                    f"/api/v1/ticket-drafts/{duplicate['id']}/submit",
                    headers={**CUSTOMER, "Idempotency-Key": "perf-duplicate-storm"},
                    json={"row_version": duplicate["row_version"]},
                )
                for _ in range(8)
            ]
            return await asyncio.gather(*same_key)

        storm = _run(app, duplicate_storm)
    assert [response.status_code for response in submissions] == [201] * SUBMISSION_BATCH
    keys = {response.json()["key"] for response in submissions}
    assert len(keys) == SUBMISSION_BATCH
    assert elapsed < 30, f"submission batch took {elapsed:.1f}s"
    assert sorted(response.status_code for response in storm) == [200] * 7 + [201]
    after = int(_psql("SELECT count(*) FROM itsm.ticket"))
    assert after == before + SUBMISSION_BATCH + 1


@pytest.mark.integration
def test_queue_pagination_over_backlog_meets_latency_budget() -> None:
    from fastapi.testclient import TestClient

    app = create_app(_settings(), resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        queues = client.get("/api/v1/agent/queues", headers=AGENT)
        assert queues.status_code == 200
        queue_id = queues.json()["items"][0]["id"]
        samples: list[float] = []
        for _ in range(10):
            started = time.perf_counter()
            page = client.get(f"/api/v1/agent/queues/{queue_id}/tickets?limit=50", headers=AGENT)
            samples.append(time.perf_counter() - started)
            assert page.status_code == 200, page.text
            assert len(page.json()["items"]) > 0
    assert _p95(samples) < P95_BUDGET_SECONDS, f"queue p95={_p95(samples):.3f}s"


@pytest.mark.integration
def test_database_pool_sizing_sustains_concurrency_beyond_pool_capacity() -> None:
    from fastapi.testclient import TestClient

    app = create_app(
        _settings(database_pool_size=3, database_max_overflow=2),
        resource_factory=_resources,
    )
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        assert client.get("/api/v1/my/tickets", headers=CUSTOMER).status_code == 200

        async def burst(client_async: httpx.AsyncClient) -> list[tuple[int, float]]:
            return await asyncio.gather(
                *[_timed_get(client_async, "/api/v1/my/tickets", CUSTOMER) for _ in range(20)]
            )

        results = _run(app, burst)
        pool = app.state.resources.database.engine.pool
        assert [status for status, _ in results] == [200] * 20
        assert pool.checkedout() == 0
    settings = _settings()
    assert settings.database_pool_size >= 5
    assert settings.database_max_overflow >= 5
    assert settings.database_pool_timeout >= 10
