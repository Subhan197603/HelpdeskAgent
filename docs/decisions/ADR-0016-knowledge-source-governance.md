# ADR-0016: Knowledge source governance boundary

## Status

Accepted for Milestone 6, Task 6.1.

Approved migration: 0012_knowledge_source_governance

## Decision

Extend the physical-baseline `kb.source` aggregate rather than create a second
source registry. A source carries tenant/global scope, audience, lifecycle,
approval, owner, product/module/release, language, and optimistic-version state.

External acquisition permission is an append-only decision bound to the exact
source row version and canonical location. Any source change invalidates the
previous decision. Runtime permission evaluation also requires an active and
approved source. Oracle automated acquisition has a separate deployment kill
switch which defaults to disabled.

Task 6.1 exposes governance and permission evaluation only. It performs no
network request, document acquisition, upload, parsing, or publication.

## Consequences

Knowledge authors cannot approve their own configuration through author
permissions, ordinary employees cannot use administration routes, and every
mutation writes immutable audit evidence. A future acquisition worker must call
the same fail-closed permission gate before any external request.
