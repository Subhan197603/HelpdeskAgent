"""API unit-test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.settings import Settings
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app


class FakeProbe:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False

    async def check(self) -> bool:
        return self.healthy

    async def close(self) -> None:
        self.closed = True


def make_test_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": "postgresql+psycopg://test:test@localhost/test",
        "redis_url": "redis://localhost:6379/15",
        "object_storage_enabled": True,
        "trusted_hosts": ["testserver"],
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
def fake_resources() -> ApplicationResources:
    return ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())


@pytest.fixture
def client(fake_resources: ApplicationResources) -> Iterator[TestClient]:
    app = create_app(make_test_settings(), resource_factory=lambda _: fake_resources)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
