# ADR-0018: Versioned knowledge processing and publication

Status: Accepted for Milestone 6, Task 6.3.

Migration revision: `0014_knowledge_processing`.

## Decision

Treat parsing, chunking, and embedding output as an immutable processing version beneath an acquired
document version. Parser, chunker, configuration hash, and embedding-model identity are pinned on
that record. Reprocessing with an unchanged tuple is idempotent; changing any pinned component
creates another processing version and never overwrites a published corpus.

Chunks carry tenant, document, source, audience, and security lineage so authorization attributes
cannot be lost between publication and retrieval. Publication remains an explicit human-authorized
operation. It atomically selects a validated processing version, retires the prior current document
version, and appends immutable evidence. Failed extraction, incomplete embeddings, unapproved
documents, and invalid permissions fail closed.

The embedding boundary is provider-independent. Development and tests may use a deterministic
non-semantic provider; production rejects it and requires an approved HTTPS provider configured by
environment secret. Retrieval APIs and ranking remain Milestone 7.
