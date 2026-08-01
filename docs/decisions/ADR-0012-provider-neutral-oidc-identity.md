# ADR-0012: Provider-neutral OIDC identity boundary

- Status: Accepted
- Date: 2026-08-01

## Context

Production callers need enterprise OIDC authentication without coupling authorization or tenant
selection to Microsoft Entra ID, Oracle Identity Cloud Service, or caller-controlled claims.
External subjects must remain stable across profile changes, and temporary provider failures and
signing-key rotation must fail predictably without storing bearer credentials.

## Decision

- Validate bearer JWTs against exact configured OIDC discovery and JWKS metadata with asymmetric
  algorithm allowlists, bounded caching/timeouts, controlled key refresh, and bounded stale use.
- Resolve tenants only through server-managed provider, issuer, and optional organization mappings.
- Persist a durable external-subject-to-local-user link; never persist tokens or raw claim sets.
- Keep PostgreSQL roles, groups, business units, active state, and permission policy authoritative.
- Make JIT provisioning opt-in and privilege-free, and restrict profile synchronization to display
  name, email, and locale.
- Use the existing request context, unit of work, transaction-local tenant context, audit stream,
  and centralized authorization path for both developer and OIDC modes.

## Alternatives

Provider-specific SDK coupling, accepting unsigned/introspected claims from a proxy, deriving
tenants or roles directly from token claims, storing bearer tokens, and silently falling back to
developer identity were rejected.

## Consequences

Operators must maintain tenant mappings and issuer/audience configuration. Key rotation tolerates
provider overlap and bounded temporary outages but fails closed after stale-cache expiry. External
group-to-local-membership synchronization remains a separately governed feature. Interactive
authorization-code/PKCE handling belongs to a frontend or gateway and is outside this API task.
