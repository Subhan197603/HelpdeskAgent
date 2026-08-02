# ADR-0015: Notification delivery and retry state

## Status

Accepted for Milestone 5, Task 5.3.

Approved migration: 0011_notification_delivery

## Decision

Business transactions continue to write notification-intent outbox facts. The
worker first converts each fact into one version-pinned email delivery and one
version-pinned in-app notification per authorized recipient. Database uniqueness
constraints make this planning step idempotent.

Email sending is a separate leased operation. Every attempt is append-only,
records only a sanitized error code, and uses exponential backoff with bounded
jitter. Permanent failures and attempts that exhaust the configured limit are
excluded from further claims. SMTP messages use a deterministic Message-ID.

Templates use a deliberately non-executable `{{ variable }}` language with a
fixed allowlist. HTML substitutions are escaped. Initial runtime templates do
not expose ticket descriptions, comments, internal notes, or email bodies.

## Consequences

The selected immutable template version remains auditable for email and in-app
delivery. A provider that does not honor Message-ID deduplication can still
deliver twice if a process crashes after SMTP accepts a message but before the
database records success; this is an inherent SMTP boundary and is mitigated by
the stable Message-ID and delivery lease.
