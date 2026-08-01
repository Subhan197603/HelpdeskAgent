"""Provider-neutral OIDC discovery, JWKS caching, and bearer-token validation."""

import asyncio
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import exceptions as jwt_exceptions

from apps.api.app.core.exceptions import AuthenticationError, ExternalDependencyError
from apps.api.app.core.settings import Settings

logger = logging.getLogger(__name__)
_MAX_TOKEN_LENGTH = 16_384
_CACHE_MAX_AGE = re.compile(r"(?:^|,)\s*max-age=(\d+)\s*(?:,|$)", re.IGNORECASE)


class OidcFailureReason(StrEnum):
    MALFORMED_TOKEN = "malformed_token"
    UNSIGNED_TOKEN = "unsigned_token"
    DISALLOWED_ALGORITHM = "disallowed_algorithm"
    UNKNOWN_KEY = "unknown_key"
    INVALID_SIGNATURE = "invalid_signature"
    INCORRECT_ISSUER = "incorrect_issuer"
    INCORRECT_AUDIENCE = "incorrect_audience"
    EXPIRED_TOKEN = "expired_token"
    PREMATURE_TOKEN = "premature_token"
    MISSING_SUBJECT = "missing_subject"
    MISSING_REQUIRED_CLAIM = "missing_required_claim"
    INVALID_CLAIMS = "invalid_claims"
    INVALID_AUTHORIZED_PARTY = "invalid_authorized_party"
    INVALID_TOKEN_TYPE = "invalid_token_type"


class OidcAuthenticationError(AuthenticationError):
    def __init__(self, reason: OidcFailureReason) -> None:
        super().__init__(
            "Bearer token is invalid.", headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        )
        self.reason = reason


class OidcProviderError(ExternalDependencyError):
    def __init__(self) -> None:
        super().__init__("OIDC provider is temporarily unavailable.")


@dataclass(frozen=True, slots=True)
class ValidatedOidcIdentity:
    provider_code: str
    issuer: str
    subject: str
    organization: str | None
    display_name: str | None
    email: str | None
    locale: str | None
    external_groups: tuple[str, ...]


@dataclass(slots=True)
class AuthenticationMetrics:
    """Bounded in-process counters using only configured and enumerated labels."""

    successes: int = 0
    failures: Counter[str] = field(default_factory=Counter)
    discovery_failures: int = 0
    discovery_latency_ms_total: float = 0.0
    discovery_requests: int = 0
    jwks_refreshes: int = 0
    unknown_signing_keys: int = 0
    jit_provisioned: int = 0
    profiles_synchronized: int = 0
    authorization_denials: int = 0

    def snapshot(self) -> dict[str, int | float | dict[str, int]]:
        return {
            "authentication_successes": self.successes,
            "authentication_failures": dict(sorted(self.failures.items())),
            "discovery_failures": self.discovery_failures,
            "discovery_requests": self.discovery_requests,
            "discovery_latency_ms_total": round(self.discovery_latency_ms_total, 3),
            "jwks_refreshes": self.jwks_refreshes,
            "unknown_signing_keys": self.unknown_signing_keys,
            "jit_provisioned": self.jit_provisioned,
            "profiles_synchronized": self.profiles_synchronized,
            "authorization_denials": self.authorization_denials,
        }


@dataclass(frozen=True, slots=True)
class _Discovery:
    issuer: str
    jwks_uri: str


@dataclass(slots=True)
class _CacheEntry:
    value: Any
    expires_at: float
    stale_until: float


class OidcProviderClient:
    """Fetch and cache one configured provider's discovery metadata and signing keys."""

    def __init__(
        self,
        settings: Settings,
        metrics: AuthenticationMetrics,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.oidc_issuer_url:
            raise ValueError("OIDC issuer is not configured")
        self._issuer = settings.oidc_issuer_url
        self._timeout = settings.oidc_discovery_timeout_seconds
        self._cache_seconds = settings.oidc_jwks_cache_seconds
        self._stale_seconds = settings.oidc_jwks_stale_if_error_seconds
        self._require_https = settings.is_production
        self._metrics = metrics
        self._client = client or httpx.AsyncClient(timeout=self._timeout)
        self._owns_client = client is None
        self._discovery: _CacheEntry | None = None
        self._jwks: _CacheEntry | None = None
        self._discovery_lock = asyncio.Lock()
        self._jwks_lock = asyncio.Lock()
        self._unknown_key_refresh: dict[str, float] = {}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _ttl(response: httpx.Response, configured: int) -> int:
        match = _CACHE_MAX_AGE.search(response.headers.get("Cache-Control", ""))
        if match is None:
            return configured
        return max(60, min(configured, int(match.group(1))))

    def _validate_remote_url(self, value: str) -> str:
        parsed = urlsplit(value)
        if not parsed.netloc or parsed.scheme not in {"http", "https"}:
            raise OidcProviderError()
        if self._require_https and parsed.scheme != "https":
            raise OidcProviderError()
        return value

    async def _fetch_json(self, url: str, operation: str) -> tuple[dict[str, Any], int]:
        started = time.perf_counter()
        try:
            response = await self._client.get(url, timeout=self._timeout)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("OIDC response is not an object")
            return payload, self._ttl(response, self._cache_seconds)
        except (httpx.HTTPError, ValueError):
            logger.warning(
                "OIDC provider request failed",
                extra={"oidc_operation": operation, "outcome": "failure"},
            )
            raise OidcProviderError() from None
        finally:
            if operation == "discovery":
                self._metrics.discovery_requests += 1
                self._metrics.discovery_latency_ms_total += (time.perf_counter() - started) * 1000

    async def discovery(self) -> _Discovery:
        now = time.monotonic()
        if self._discovery is not None and self._discovery.expires_at > now:
            return cast("_Discovery", self._discovery.value)
        async with self._discovery_lock:
            now = time.monotonic()
            if self._discovery is not None and self._discovery.expires_at > now:
                return cast("_Discovery", self._discovery.value)
            try:
                payload, ttl = await self._fetch_json(
                    f"{self._issuer}/.well-known/openid-configuration", "discovery"
                )
                issuer = payload.get("issuer")
                jwks_uri = payload.get("jwks_uri")
                if issuer != self._issuer or not isinstance(jwks_uri, str):
                    raise OidcProviderError()
                value = _Discovery(issuer, self._validate_remote_url(jwks_uri))
                self._discovery = _CacheEntry(value, now + ttl, now + ttl + self._stale_seconds)
                return value
            except OidcProviderError:
                self._metrics.discovery_failures += 1
                if self._discovery is not None and self._discovery.stale_until > now:
                    return cast("_Discovery", self._discovery.value)
                raise

    async def _load_jwks(self, *, force: bool) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if not force and self._jwks is not None and self._jwks.expires_at > now:
            return cast("dict[str, dict[str, Any]]", self._jwks.value)
        async with self._jwks_lock:
            now = time.monotonic()
            if not force and self._jwks is not None and self._jwks.expires_at > now:
                return cast("dict[str, dict[str, Any]]", self._jwks.value)
            try:
                discovery = await self.discovery()
                payload, ttl = await self._fetch_json(discovery.jwks_uri, "jwks")
                keys = payload.get("keys")
                if not isinstance(keys, list) or len(keys) > 100:
                    raise OidcProviderError()
                indexed = {
                    key["kid"]: key
                    for key in keys
                    if isinstance(key, dict) and isinstance(key.get("kid"), str)
                }
                if not indexed:
                    raise OidcProviderError()
                self._jwks = _CacheEntry(indexed, now + ttl, now + ttl + self._stale_seconds)
                self._metrics.jwks_refreshes += 1
                return indexed
            except OidcProviderError:
                if self._jwks is not None and self._jwks.stale_until > now:
                    return cast("dict[str, dict[str, Any]]", self._jwks.value)
                raise

    async def signing_key(self, key_id: str) -> dict[str, Any]:
        keys = await self._load_jwks(force=False)
        if key_id in keys:
            return keys[key_id]
        self._metrics.unknown_signing_keys += 1
        now = time.monotonic()
        last_refresh = self._unknown_key_refresh.get(key_id, 0.0)
        if now - last_refresh >= 5.0:
            self._unknown_key_refresh[key_id] = now
            keys = await self._load_jwks(force=True)
        if key_id not in keys:
            raise OidcAuthenticationError(OidcFailureReason.UNKNOWN_KEY)
        return keys[key_id]


class OidcTokenValidator:
    def __init__(
        self, settings: Settings, provider: OidcProviderClient, metrics: AuthenticationMetrics
    ) -> None:
        if (
            not settings.oidc_provider_code
            or not settings.oidc_issuer_url
            or not settings.oidc_audience
        ):
            raise ValueError("OIDC token validator requires complete settings")
        self._settings = settings
        self._provider = provider
        self._metrics = metrics

    def _failure(self, reason: OidcFailureReason) -> OidcAuthenticationError:
        self._metrics.failures[reason.value] += 1
        return OidcAuthenticationError(reason)

    async def validate(self, token: str) -> ValidatedOidcIdentity:
        if not token or len(token) > _MAX_TOKEN_LENGTH or token.count(".") != 2:
            raise self._failure(OidcFailureReason.MALFORMED_TOKEN)
        try:
            header = jwt.get_unverified_header(token)
        except jwt_exceptions.DecodeError:
            raise self._failure(OidcFailureReason.MALFORMED_TOKEN) from None
        algorithm = header.get("alg")
        if algorithm == "none":
            raise self._failure(OidcFailureReason.UNSIGNED_TOKEN)
        if algorithm not in self._settings.oidc_allowed_algorithms:
            raise self._failure(OidcFailureReason.DISALLOWED_ALGORITHM)
        key_id = header.get("kid")
        if not isinstance(key_id, str) or not key_id:
            raise self._failure(OidcFailureReason.UNKNOWN_KEY)
        if (
            self._settings.oidc_required_token_type
            and header.get("typ") != self._settings.oidc_required_token_type
        ):
            raise self._failure(OidcFailureReason.INVALID_TOKEN_TYPE)
        try:
            jwk = await self._provider.signing_key(key_id)
        except OidcAuthenticationError as exc:
            self._metrics.failures[exc.reason.value] += 1
            raise
        try:
            signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self._settings.oidc_allowed_algorithms,
                issuer=self._settings.oidc_issuer_url,
                audience=self._settings.oidc_audience,
                leeway=self._settings.oidc_clock_skew_seconds,
                options={"require": self._settings.oidc_required_claims},
            )
        except jwt_exceptions.ExpiredSignatureError:
            raise self._failure(OidcFailureReason.EXPIRED_TOKEN) from None
        except jwt_exceptions.ImmatureSignatureError:
            raise self._failure(OidcFailureReason.PREMATURE_TOKEN) from None
        except jwt_exceptions.InvalidIssuerError:
            raise self._failure(OidcFailureReason.INCORRECT_ISSUER) from None
        except jwt_exceptions.InvalidAudienceError:
            raise self._failure(OidcFailureReason.INCORRECT_AUDIENCE) from None
        except jwt_exceptions.InvalidSignatureError:
            raise self._failure(OidcFailureReason.INVALID_SIGNATURE) from None
        except jwt_exceptions.MissingRequiredClaimError as exc:
            reason = (
                OidcFailureReason.MISSING_SUBJECT
                if exc.claim == "sub"
                else OidcFailureReason.MISSING_REQUIRED_CLAIM
            )
            raise self._failure(reason) from None
        except (jwt_exceptions.InvalidAlgorithmError, jwt_exceptions.DecodeError, ValueError):
            raise self._failure(OidcFailureReason.INVALID_CLAIMS) from None
        except jwt_exceptions.PyJWTError:
            raise self._failure(OidcFailureReason.INVALID_CLAIMS) from None

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 300:
            raise self._failure(OidcFailureReason.MISSING_SUBJECT)
        if (
            self._settings.oidc_authorized_party
            and claims.get("azp") != self._settings.oidc_authorized_party
        ):
            raise self._failure(OidcFailureReason.INVALID_AUTHORIZED_PARTY)
        organization: str | None = None
        if self._settings.oidc_organization_claim:
            candidate = claims.get(self._settings.oidc_organization_claim)
            if not isinstance(candidate, str) or not candidate or len(candidate) > 300:
                raise self._failure(OidcFailureReason.INVALID_CLAIMS)
            organization = candidate

        mappings = self._settings.oidc_claim_mappings
        display_name = _optional_string(claims.get(mappings.get("display_name", "")), 250)
        email = _optional_string(claims.get(mappings.get("email", "")), 320)
        locale = _optional_string(claims.get(mappings.get("locale", "")), 20)
        group_claim = claims.get(mappings.get("groups", ""), [])
        groups = (
            tuple(item for item in group_claim[:200] if isinstance(item, str) and len(item) <= 300)
            if isinstance(group_claim, list)
            else ()
        )
        return ValidatedOidcIdentity(
            cast("str", self._settings.oidc_provider_code),
            cast("str", self._settings.oidc_issuer_url),
            subject,
            organization,
            display_name,
            email,
            locale,
            groups,
        )


def _optional_string(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= maximum else None
