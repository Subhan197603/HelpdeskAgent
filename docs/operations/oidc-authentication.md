# Production OIDC authentication

## Trust boundary

The API accepts provider-neutral OIDC bearer tokens when `OIDC_ENABLED=true`. It validates the
token locally against the configured issuer's discovery document and JWKS: signature, asymmetric
algorithm allowlist, issuer, audience, expiry, not-before time, required claims, subject, and
optional authorized-party, organization, and token-type constraints. An invalid bearer token never
falls back to developer identity. Supplying both mechanisms is rejected.

OIDC claims identify an external principal; they do not grant application privileges. The server
maps `(provider_code, trusted_issuer, organization_claim_value)` to a tenant and maps the external
subject to a durable local user. Effective roles, support groups, business unit, active state, and
permissions always come from PostgreSQL. External group claims are observed only; group-to-role
synchronization is intentionally not implemented in this milestone.

## Configuration

Start with `.env.example`. Production requires OIDC, a client ID, an HTTPS issuer, and all existing
production safety settings. Common settings are:

```dotenv
OIDC_ENABLED=true
OIDC_PROVIDER_CODE=ENTERPRISE_OIDC
OIDC_ISSUER_URL=https://identity.example.com/tenant/v2.0
OIDC_CLIENT_ID=helpdesk-web
OIDC_AUDIENCE=api://helpdesk-api
OIDC_ALLOWED_ALGORITHMS=["RS256"]
OIDC_REQUIRED_CLAIMS=["sub","exp"]
OIDC_JIT_PROVISIONING_ENABLED=false
OIDC_PROFILE_SYNCHRONIZATION_ENABLED=true
OIDC_GROUP_SYNCHRONIZATION_ENABLED=false
```

For Microsoft Entra ID, use the exact tenant-specific issuer returned by its discovery document;
do not use a broad multi-tenant issuer unless the server-side organization mapping is deliberately
configured. For Oracle Identity Cloud Service, use the tenant's exact issuer and API audience.
Provider client secrets, when a separate frontend authorization-code flow needs one, belong in a
secret manager and must never be committed. The API bearer-token validator does not need to store
access, ID, or refresh tokens.

Optional hardening settings include `OIDC_AUTHORIZED_PARTY`, `OIDC_REQUIRED_TOKEN_TYPE`,
`OIDC_ORGANIZATION_CLAIM`, clock skew, discovery timeout, JWKS cache lifetime, and stale-on-error
duration. Only `display_name`, `email`, `locale`, and `groups` claim mappings are accepted.

## Tenant mapping and user lifecycle

Create `identity.oidc_tenant_mapping` rows through an administrator-controlled deployment process,
not from caller claims. A mapping may use an organization claim to distinguish tenants sharing one
issuer. Deactivate mappings or `identity.external_identity` rows to revoke access without deleting
audit history.

With JIT disabled, an unknown external subject receives 401. With JIT enabled, a valid email is
required and the service creates only a local user and external-identity link. It assigns no role,
support group, business unit, project, or administrative privilege. Profile synchronization can
update only display name, email, and locale. The local role and membership tables remain
authoritative.

Revision `0004_oidc_external_identity` owns these post-baseline objects. Apply and verify it with
the commands in [the migration guide](database-migrations.md). The approved physical baseline is
unchanged.

## Operations and failure behavior

Discovery and JWKS requests have bounded timeouts. Valid metadata and keys are cached, an unknown
key ID triggers a controlled refresh, and a bounded stale cache may cover a temporary provider
failure. Once stale data expires, authentication returns 503 rather than accepting an unverified
token. Logs and responses contain no raw token, claims, subject, cookies, or provider payload.

`GET /api/v1/me` reports `authentication_mode=oidc` and the safe provider code. The privileged
diagnostic endpoint reports only sanitized configuration flags and bounded counters. In production
it returns 404 unless `OIDC_DIAGNOSTICS_ENABLED=true`, and still requires `ADMIN_IDENTITY_READ`.

Security events cover success, signature/issuer/audience/expiry rejection, provider failure,
mapping failure, inactive identities, JIT creation, profile synchronization, authorization denial,
and privileged diagnostic access. Subjects are represented only by a truncated SHA-256 digest.

Validate changes with `uv run pytest apps/api/tests/test_oidc.py`, the normal unit suite, and the
PostgreSQL integration suite. Rotate keys at the provider first, retain overlap through the cache
window, then remove the old key. A burst of unknown-key or provider-failure counters should be
investigated before extending cache lifetimes.
