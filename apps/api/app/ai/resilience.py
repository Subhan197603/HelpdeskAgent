"""Bounded provider retries, explicit fallback, cancellation, and circuit breaking."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from apps.api.app.ai.models import LLMResult, ProviderRequest
from apps.api.app.ai.providers import LLMProvider, ProviderError


class CircuitOpenError(ProviderError):
    def __init__(self) -> None:
        super().__init__("PROVIDER_CIRCUIT_OPEN")


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None


@dataclass(frozen=True, slots=True)
class CircuitObservation:
    provider_alias: str
    model_alias: str
    state: str
    recent_failures: int
    recovery_seconds_remaining: float | None


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._clock = clock
        self._states: dict[tuple[str, str], _CircuitState] = {}
        self._lock = asyncio.Lock()

    async def permit(self, provider: LLMProvider) -> None:
        async with self._lock:
            state = self._states.setdefault(_key(provider), _CircuitState())
            if state.opened_at is None:
                return
            if self._clock() - state.opened_at < self._recovery_seconds:
                raise CircuitOpenError()
            state.opened_at = None
            state.failures = 0

    async def success(self, provider: LLMProvider) -> None:
        async with self._lock:
            self._states[_key(provider)] = _CircuitState()

    async def failure(self, provider: LLMProvider) -> None:
        async with self._lock:
            state = self._states.setdefault(_key(provider), _CircuitState())
            state.failures += 1
            if state.failures >= self._failure_threshold:
                state.opened_at = self._clock()

    async def snapshot(
        self, known_models: Iterable[tuple[str, str]] = ()
    ) -> tuple[CircuitObservation, ...]:
        """Return a current-process observation without probing or resetting a provider."""
        async with self._lock:
            now = self._clock()
            keys = set(known_models) | set(self._states)
            observations: list[CircuitObservation] = []
            for provider_alias, model_alias in sorted(keys):
                state = self._states.get((provider_alias, model_alias))
                if state is None:
                    observations.append(
                        CircuitObservation(provider_alias, model_alias, "not_observed", 0, None)
                    )
                    continue
                remaining = (
                    max(0.0, self._recovery_seconds - (now - state.opened_at))
                    if state.opened_at is not None
                    else None
                )
                observations.append(
                    CircuitObservation(
                        provider_alias,
                        model_alias,
                        "open" if remaining is not None and remaining > 0 else "closed",
                        state.failures if remaining is None or remaining > 0 else 0,
                        remaining if remaining is not None and remaining > 0 else None,
                    )
                )
            return tuple(observations)


class ResilientProviderExecutor:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        maximum_attempts: int,
        circuit_breaker: CircuitBreaker,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._maximum_attempts = maximum_attempts
        self._circuit = circuit_breaker
        self._sleeper = sleeper

    async def generate(
        self,
        primary: LLMProvider,
        request: ProviderRequest,
        *,
        fallback: LLMProvider | None = None,
    ) -> LLMResult:
        try:
            return await self._attempt(primary, request)
        except (ProviderError, TimeoutError):
            if fallback is None:
                raise
            return await self._attempt(fallback, request)

    async def _attempt(self, provider: LLMProvider, request: ProviderRequest) -> LLMResult:
        last_error: ProviderError | TimeoutError | None = None
        for attempt in range(self._maximum_attempts):
            await self._circuit.permit(provider)
            try:
                result = await asyncio.wait_for(
                    provider.generate(request), timeout=self._timeout_seconds
                )
            except TimeoutError as error:
                last_error = error
                await self._circuit.failure(provider)
                if attempt + 1 < self._maximum_attempts:
                    await self._sleeper(min(0.1 * (2**attempt), 2.0))
                continue
            except ProviderError as error:
                last_error = error
                await self._circuit.failure(provider)
                if not error.retryable:
                    raise
                if attempt + 1 < self._maximum_attempts:
                    await self._sleeper(min(0.1 * (2**attempt), 2.0))
                continue
            await self._circuit.success(provider)
            return result
        assert last_error is not None
        raise last_error


def _key(provider: LLMProvider) -> tuple[str, str]:
    return provider.provider_alias, provider.model_alias
