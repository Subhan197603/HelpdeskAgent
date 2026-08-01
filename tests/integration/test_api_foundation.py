"""Real PostgreSQL, Redis, object-storage, and API-container checks."""

import asyncio
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.core.context import RequestContext
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.infrastructure.redis_health import RedisHealthProbe

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PROJECT = "fusion-helpdesk-api-test"
POSTGRES_PORT = "55440"
REDIS_PORT = "56380"
API_PORT = "58000"


@pytest.fixture(scope="module")
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_HOST_PORT": POSTGRES_PORT,
            "REDIS_HOST_PORT": REDIS_PORT,
            "MINIO_API_HOST_PORT": "59010",
            "MINIO_CONSOLE_HOST_PORT": "59011",
            "API_HOST_PORT": API_PORT,
        }
    )
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", "compose", "--project-name", COMPOSE_PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and completed.returncode != 0:
        pytest.fail(
            f"Docker Compose failed ({completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


@pytest.fixture(scope="module", autouse=True)
def api_stack() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres", "redis", "minio")
    try:
        _compose("run", "--rm", "minio-init")
        _compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "helpdesk",
            "-f",
            "/baseline/install_all.sql",
        )
        _compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "app_password=helpdesk",
            "-U",
            "postgres",
            "-d",
            "helpdesk",
            "-f",
            "/runtime-config/configure_local_runtime.sql",
        )
        _compose("--profile", "application", "up", "-d", "--build", "api")
        for _ in range(30):
            try:
                response = httpx.get(f"http://127.0.0.1:{API_PORT}/health/live", timeout=2)
                if response.is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        else:
            logs = _compose("logs", "api", check=False)
            pytest.fail(f"API did not become healthy.\n{logs.stdout}\n{logs.stderr}")
        yield
    finally:
        _compose("--profile", "application", "down", "--volumes", "--remove-orphans", check=False)


def _context() -> RequestContext:
    return RequestContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        external_subject=None,
        roles=frozenset(),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id=str(uuid4()),
        request_id=str(uuid4()),
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_transaction_context_does_not_leak_through_pool() -> None:
    engine = create_async_engine(
        f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{POSTGRES_PORT}/helpdesk",
        pool_size=1,
        max_overflow=0,
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            context = _context()
            await apply_transaction_context(session, context, rls_enabled=True)
            tenant = await session.scalar(text("SELECT current_setting('app.tenant_id')"))
            assert tenant == str(context.tenant_id)
        async with engine.connect() as connection:
            leaked = await connection.scalar(
                text("SELECT NULLIF(current_setting('app.tenant_id', true), '')")
            )
            assert leaked is None
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_redis_health_adapter() -> None:
    probe = RedisHealthProbe(f"redis://127.0.0.1:{REDIS_PORT}/0")
    try:
        assert await probe.check()
    finally:
        await probe.close()


@pytest.mark.integration
@pytest.mark.container
def test_api_container_is_healthy_and_ready() -> None:
    live = httpx.get(f"http://127.0.0.1:{API_PORT}/health/live", timeout=5)
    ready = httpx.get(f"http://127.0.0.1:{API_PORT}/health/ready", timeout=5)
    assert live.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["status"] == "healthy"
    assert ready.json()["dependencies"]["postgresql"]["status"] == "healthy"
    assert ready.json()["dependencies"]["redis"]["status"] == "healthy"
    assert ready.json()["dependencies"]["object_storage"]["status"] == "healthy"
