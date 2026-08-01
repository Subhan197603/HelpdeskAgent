"""S3-compatible object-storage health adapter."""

import httpx


class ObjectStorageHealthProbe:
    """Probe the S3 provider's readiness endpoint without transmitting credentials."""

    def __init__(self, endpoint: str) -> None:
        self._url = f"{endpoint.rstrip('/')}/minio/health/ready"

    async def check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(self._url)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        return None
