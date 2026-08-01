"""Provider-neutral dependency health contracts and resource ownership."""

import asyncio
from dataclasses import dataclass
from typing import Protocol


class HealthProbe(Protocol):
    async def check(self) -> bool: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class ApplicationResources:
    database: HealthProbe
    redis: HealthProbe
    object_storage: HealthProbe
    clamav: HealthProbe

    async def close(self) -> None:
        await asyncio.gather(
            self.database.close(),
            self.redis.close(),
            self.object_storage.close(),
            self.clamav.close(),
        )
