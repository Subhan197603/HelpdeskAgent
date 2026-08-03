"""OpenAI, Anthropic, and deterministic fake provider adapters."""

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, Protocol, cast

import httpx

from apps.api.app.ai.models import LLMResult, ModelUsage, ProviderRequest, ToolRequest


class ProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class LLMProvider(Protocol):
    provider_alias: str
    model_alias: str

    async def generate(self, request: ProviderRequest) -> LLMResult: ...


Transport = Callable[[str, dict[str, str], dict[str, Any], float], Awaitable[dict[str, Any]]]


async def _http_transport(
    endpoint: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            if response.status_code in {408, 429} or response.status_code >= 500:
                raise ProviderError("PROVIDER_RETRYABLE", retryable=True)
            if response.status_code >= 400:
                raise ProviderError("PROVIDER_REJECTED")
            value = response.json()
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError) as error:
        raise ProviderError("PROVIDER_UNAVAILABLE", retryable=True) from error
    if not isinstance(value, dict):
        raise ProviderError("INVALID_PROVIDER_RESPONSE")
    return cast("dict[str, Any]", value)


class OpenAIProvider:
    provider_alias = "openai"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model_alias: str,
        deployment: str,
        timeout: float,
        transport: Transport = _http_transport,
    ) -> None:
        _require_https(endpoint)
        self._endpoint = endpoint
        self._api_key = api_key
        self.model_alias = model_alias
        self._deployment = deployment
        self._timeout = timeout
        self._transport = transport

    async def generate(self, request: ProviderRequest) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self._deployment,
            "instructions": request.instructions,
            "input": list(request.messages),
            "tools": [
                {
                    "type": "function",
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["input_schema"],
                }
                for item in request.tools
            ],
            "metadata": request.metadata,
        }
        if request.maximum_output_tokens is not None:
            payload["max_output_tokens"] = request.maximum_output_tokens
        raw = await self._transport(
            self._endpoint,
            {"Authorization": f"Bearer {self._api_key}"},
            payload,
            self._timeout,
        )
        try:
            usage = cast("dict[str, Any]", raw.get("usage", {}))
            output = cast("list[dict[str, Any]]", raw.get("output", []))
            tool_requests = tuple(
                _openai_tool_request(item) for item in output if item.get("type") == "function_call"
            )
            output_text = "".join(
                str(part.get("text", ""))
                for item in output
                if item.get("type") == "message"
                for part in cast("list[dict[str, Any]]", item.get("content", []))
                if part.get("type") == "output_text"
            )
            return LLMResult(
                text=output_text,
                tool_requests=tool_requests,
                usage=_usage(usage),
                provider=self.provider_alias,
                model=self.model_alias,
                finish_reason=str(raw.get("status", "completed")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("INVALID_PROVIDER_RESPONSE") from error


class AnthropicProvider:
    provider_alias = "anthropic"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model_alias: str,
        deployment: str,
        timeout: float,
        transport: Transport = _http_transport,
    ) -> None:
        _require_https(endpoint)
        self._endpoint = endpoint
        self._api_key = api_key
        self.model_alias = model_alias
        self._deployment = deployment
        self._timeout = timeout
        self._transport = transport

    async def generate(self, request: ProviderRequest) -> LLMResult:
        raw = await self._transport(
            self._endpoint,
            {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"},
            {
                "model": self._deployment,
                "system": request.instructions,
                "messages": list(request.messages),
                "tools": list(request.tools),
                "max_tokens": request.maximum_output_tokens or 1024,
                "metadata": request.metadata,
            },
            self._timeout,
        )
        try:
            blocks = cast("list[dict[str, Any]]", raw.get("content", []))
            text = "".join(
                str(item.get("text", "")) for item in blocks if item.get("type") == "text"
            )
            tool_requests = tuple(
                ToolRequest(
                    str(item["id"]), str(item["name"]), cast("dict[str, Any]", item["input"])
                )
                for item in blocks
                if item.get("type") == "tool_use"
            )
            return LLMResult(
                text=text,
                tool_requests=tool_requests,
                usage=_usage(cast("dict[str, Any]", raw.get("usage", {}))),
                provider=self.provider_alias,
                model=self.model_alias,
                finish_reason=str(raw.get("stop_reason", "end_turn")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("INVALID_PROVIDER_RESPONSE") from error


class FakeLLMProvider:
    provider_alias = "fake"

    def __init__(self, results: list[LLMResult], model_alias: str = "fake-model") -> None:
        self.model_alias = model_alias
        self._results = list(results)
        self.requests: list[ProviderRequest] = []

    async def generate(self, request: ProviderRequest) -> LLMResult:
        self.requests.append(request)
        if not self._results:
            raise ProviderError("FAKE_PROVIDER_EXHAUSTED")
        return self._results.pop(0)


def _usage(value: dict[str, Any]) -> ModelUsage:
    input_details = cast("dict[str, Any]", value.get("input_tokens_details", {}))
    return ModelUsage(
        input_tokens=int(value.get("input_tokens", 0)),
        output_tokens=int(value.get("output_tokens", 0)),
        cached_tokens=int(value.get("cached_tokens", input_details.get("cached_tokens", 0))),
        cost_estimate=Decimal(str(value.get("cost_estimate", "0"))),
        currency_code=str(value.get("currency_code", "USD")),
    )


def _require_https(endpoint: str) -> None:
    if not endpoint.startswith("https://"):
        raise ValueError("AI provider endpoint must use HTTPS")


def _openai_tool_request(item: dict[str, Any]) -> ToolRequest:
    arguments = item.get("arguments", {})
    if isinstance(arguments, str):
        decoded = json.loads(arguments)
        if not isinstance(decoded, dict):
            raise ProviderError("INVALID_PROVIDER_RESPONSE")
        arguments = decoded
    if not isinstance(arguments, dict):
        raise ProviderError("INVALID_PROVIDER_RESPONSE")
    return ToolRequest(
        call_id=str(item["call_id"]),
        name=str(item["name"]),
        arguments=cast("dict[str, Any]", arguments),
    )
