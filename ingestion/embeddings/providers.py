"""Batch embedding adapters with pinned model identity and dimensions."""

import hashlib
import math
from typing import Protocol, cast

import httpx


class EmbeddingError(RuntimeError):
    """Embedding generation was unavailable or returned an invalid contract."""


class EmbeddingProvider(Protocol):
    model_code: str
    dimension: int

    async def embed_batch(self, inputs: list[str]) -> list[list[float]]: ...


class DeterministicEmbeddingProvider:
    """Stable non-semantic vectors for development and deterministic tests only."""

    def __init__(self, model_code: str = "DEFAULT_1536", dimension: int = 1536) -> None:
        self.model_code = model_code
        self.dimension = dimension

    async def embed_batch(self, inputs: list[str]) -> list[list[float]]:
        return [_deterministic_vector(value, self.dimension) for value in inputs]


class HttpEmbeddingProvider:
    """OpenAI-compatible HTTPS boundary without provider-specific persistence."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model_code: str,
        dimension: int = 1536,
        timeout_seconds: float = 30,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Embedding endpoint must use HTTPS")
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout_seconds
        self.model_code = model_code
        self.dimension = dimension

    async def embed_batch(self, inputs: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.post(
                    self._endpoint,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self.model_code, "input": inputs},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EmbeddingError("EMBEDDING_PROVIDER_UNAVAILABLE") from error
        try:
            rows = sorted(payload["data"], key=lambda row: int(row["index"]))
            vectors = [cast("list[float]", row["embedding"]) for row in rows]
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingError("INVALID_EMBEDDING_RESPONSE") from error
        if len(vectors) != len(inputs) or any(len(vector) != self.dimension for vector in vectors):
            raise EmbeddingError("INVALID_EMBEDDING_DIMENSION")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise EmbeddingError("INVALID_EMBEDDING_VALUE")
        return vectors


def _deterministic_vector(value: str, dimension: int) -> list[float]:
    seed = hashlib.sha256(value.encode()).digest()
    values = [((seed[index % len(seed)] / 255.0) * 2.0) - 1.0 for index in range(dimension)]
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return [item / norm for item in values]
