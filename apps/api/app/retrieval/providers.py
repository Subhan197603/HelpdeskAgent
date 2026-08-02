"""Approved query-embedding and optional reranking provider boundaries."""

import hashlib
import math
from typing import Protocol, cast
from uuid import UUID

import httpx

from apps.api.app.retrieval.models import RetrievalCandidate


class RetrievalProviderError(RuntimeError):
    """An approved retrieval provider was unavailable or returned invalid data."""


class QueryEmbeddingProvider(Protocol):
    model_code: str

    async def embed(self, query: str) -> tuple[float, ...]: ...


class RerankingProvider(Protocol):
    async def rerank(
        self, query: str, candidates: tuple[RetrievalCandidate, ...]
    ) -> dict[UUID, float]: ...


class DeterministicQueryEmbeddingProvider:
    """Stable non-semantic query vectors for development and tests only."""

    def __init__(self, model_code: str = "DEFAULT_1536", dimension: int = 1536) -> None:
        self.model_code = model_code
        self._dimension = dimension

    async def embed(self, query: str) -> tuple[float, ...]:
        seed = hashlib.sha256(query.encode()).digest()
        values = [
            ((seed[index % len(seed)] / 255.0) * 2.0) - 1.0 for index in range(self._dimension)
        ]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return tuple(value / norm for value in values)


class HttpQueryEmbeddingProvider:
    def __init__(self, endpoint: str, api_key: str, model_code: str, timeout: float) -> None:
        _https(endpoint)
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout
        self.model_code = model_code

    async def embed(self, query: str) -> tuple[float, ...]:
        payload = await _post(
            self._endpoint,
            self._api_key,
            self._timeout,
            {"model": self.model_code, "input": [query]},
        )
        try:
            data = cast("list[dict[str, object]]", payload["data"])
            vector = cast("list[float]", data[0]["embedding"])
        except (KeyError, IndexError, TypeError) as error:
            raise RetrievalProviderError("INVALID_EMBEDDING_RESPONSE") from error
        if len(vector) != 1536 or any(not math.isfinite(value) for value in vector):
            raise RetrievalProviderError("INVALID_EMBEDDING_RESPONSE")
        return tuple(vector)


class DisabledRerankingProvider:
    async def rerank(
        self, query: str, candidates: tuple[RetrievalCandidate, ...]
    ) -> dict[UUID, float]:
        del query, candidates
        return {}


class HttpRerankingProvider:
    """HTTPS-only adapter receiving only candidates already authorized by retrieval SQL."""

    def __init__(self, endpoint: str, api_key: str, model_code: str, timeout: float) -> None:
        _https(endpoint)
        self._endpoint = endpoint
        self._api_key = api_key
        self._model_code = model_code
        self._timeout = timeout

    async def rerank(
        self, query: str, candidates: tuple[RetrievalCandidate, ...]
    ) -> dict[UUID, float]:
        payload = await _post(
            self._endpoint,
            self._api_key,
            self._timeout,
            {
                "model": self._model_code,
                "query": query,
                "documents": [
                    {"id": str(item.chunk_id), "text": item.content_text[:8000]}
                    for item in candidates
                ],
            },
        )
        try:
            values = {
                UUID(str(item["id"])): float(str(item["score"]))
                for item in cast("list[dict[str, object]]", payload["results"])
            }
        except (KeyError, TypeError, ValueError) as error:
            raise RetrievalProviderError("INVALID_RERANK_RESPONSE") from error
        allowed = {item.chunk_id for item in candidates}
        if set(values) - allowed or any(
            not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()
        ):
            raise RetrievalProviderError("INVALID_RERANK_RESPONSE")
        return values


async def _post(
    endpoint: str, api_key: str, timeout: float, payload: dict[str, object]
) -> dict[str, object]:
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RetrievalProviderError("RETRIEVAL_PROVIDER_UNAVAILABLE") from error
    if not isinstance(result, dict):
        raise RetrievalProviderError("INVALID_RETRIEVAL_PROVIDER_RESPONSE")
    return cast("dict[str, object]", result)


def _https(endpoint: str) -> None:
    if not endpoint.startswith("https://"):
        raise ValueError("Retrieval provider endpoint must use HTTPS")
