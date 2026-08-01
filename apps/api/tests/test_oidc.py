"""OIDC discovery, JWKS caching, and token-validation security tests."""

import base64
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.app.identity.oidc import (
    AuthenticationMetrics,
    OidcAuthenticationError,
    OidcFailureReason,
    OidcProviderClient,
    OidcProviderError,
    OidcTokenValidator,
)

from .conftest import make_test_settings

ISSUER = "https://identity.example.test/issuer"
AUDIENCE = "helpdesk-api"


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _key(key_id: str) -> tuple[rsa.RSAPrivateKey, dict[str, str]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    return private, {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


def _claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "enterprise-user-1",
        "iat": now,
        "exp": now + 300,
        "name": "Enterprise User",
        "email": "user@example.test",
        "locale": "en-GB",
        "groups": ["UNTRUSTED_ADMIN"],
    }
    claims.update(overrides)
    return claims


def _token(
    private: rsa.RSAPrivateKey,
    key_id: str = "key-1",
    **claims: object,
) -> str:
    return jwt.encode(_claims(**claims), private, algorithm="RS256", headers={"kid": key_id})


def _settings(**overrides: object) -> Any:
    return make_test_settings(
        oidc_enabled=True,
        oidc_provider_code="TEST_OIDC",
        oidc_issuer_url=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_clock_skew_seconds=0,
        **overrides,
    )


def _provider(
    jwks: list[dict[str, str]],
    metrics: AuthenticationMetrics,
    *,
    fail: list[bool] | None = None,
    requests: list[str] | None = None,
) -> OidcProviderClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        if fail and fail[0]:
            raise httpx.ReadTimeout("provider unavailable", request=request)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/keys"},
                headers={"Cache-Control": "max-age=60"},
            )
        return httpx.Response(
            200,
            json={"keys": jwks},
            headers={"Cache-Control": "max-age=60"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OidcProviderClient(_settings(), metrics, client=client)


@pytest.mark.anyio
async def test_valid_signed_token_maps_only_approved_profile_claims() -> None:
    private, public = _key("key-1")
    metrics = AuthenticationMetrics()
    provider = _provider([public], metrics)
    identity = await OidcTokenValidator(_settings(), provider, metrics).validate(_token(private))
    await provider.close()

    assert identity.subject == "enterprise-user-1"
    assert identity.display_name == "Enterprise User"
    assert identity.email == "user@example.test"
    assert identity.external_groups == ("UNTRUSTED_ADMIN",)
    assert metrics.jwks_refreshes == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"iss": "https://attacker.example.test"}, OidcFailureReason.INCORRECT_ISSUER),
        ({"aud": "different-api"}, OidcFailureReason.INCORRECT_AUDIENCE),
        ({"exp": 1}, OidcFailureReason.EXPIRED_TOKEN),
        ({"nbf": int(time.time()) + 300}, OidcFailureReason.PREMATURE_TOKEN),
        ({"sub": ""}, OidcFailureReason.MISSING_SUBJECT),
    ],
)
async def test_invalid_claims_are_rejected(
    mutation: dict[str, object], reason: OidcFailureReason
) -> None:
    private, public = _key("key-1")
    metrics = AuthenticationMetrics()
    provider = _provider([public], metrics)
    with pytest.raises(OidcAuthenticationError) as caught:
        await OidcTokenValidator(_settings(), provider, metrics).validate(
            _token(private, key_id="key-1", **mutation)
        )
    await provider.close()
    assert caught.value.reason is reason


@pytest.mark.anyio
async def test_invalid_signature_unsigned_and_disallowed_tokens_are_rejected() -> None:
    trusted_private, public = _key("key-1")
    attacker_private, _ = _key("attacker")
    metrics = AuthenticationMetrics()
    provider = _provider([public], metrics)
    validator = OidcTokenValidator(_settings(), provider, metrics)

    cases = [
        (_token(attacker_private), OidcFailureReason.INVALID_SIGNATURE),
        (
            jwt.encode(_claims(), key="", algorithm="none", headers={"kid": "key-1"}),
            OidcFailureReason.UNSIGNED_TOKEN,
        ),
        (
            jwt.encode(_claims(), key="a" * 32, algorithm="HS256", headers={"kid": "key-1"}),
            OidcFailureReason.DISALLOWED_ALGORITHM,
        ),
    ]
    for token, reason in cases:
        with pytest.raises(OidcAuthenticationError) as caught:
            await validator.validate(token)
        assert caught.value.reason is reason
    await provider.close()
    assert trusted_private is not None


@pytest.mark.anyio
async def test_unknown_key_forces_one_refresh_and_key_rotation_succeeds() -> None:
    first_private, first_public = _key("key-1")
    second_private, second_public = _key("key-2")
    keys = [first_public]
    requests: list[str] = []
    metrics = AuthenticationMetrics()
    provider = _provider(keys, metrics, requests=requests)
    validator = OidcTokenValidator(_settings(), provider, metrics)

    await validator.validate(_token(first_private))
    keys.append(second_public)
    rotated = await validator.validate(_token(second_private, "key-2"))
    with pytest.raises(OidcAuthenticationError) as caught:
        await validator.validate(_token(second_private, "missing"))
    await provider.close()

    assert rotated.subject == "enterprise-user-1"
    assert caught.value.reason is OidcFailureReason.UNKNOWN_KEY
    assert len([url for url in requests if url.endswith("/keys")]) == 3


@pytest.mark.anyio
async def test_provider_timeout_is_controlled_and_stale_keys_cover_temporary_failure() -> None:
    private, public = _key("key-1")
    failure = [False]
    metrics = AuthenticationMetrics()
    provider = _provider([public], metrics, fail=failure)
    validator = OidcTokenValidator(_settings(), provider, metrics)
    await validator.validate(_token(private))

    assert provider._jwks is not None  # noqa: SLF001 - explicitly exercising cache expiry
    provider._jwks.expires_at = 0  # noqa: SLF001
    failure[0] = True
    cached = await validator.validate(_token(private))
    assert cached.subject == "enterprise-user-1"

    unavailable = _provider([public], AuthenticationMetrics(), fail=[True])
    with pytest.raises(OidcProviderError):
        await unavailable.discovery()
    await provider.close()
    await unavailable.close()
