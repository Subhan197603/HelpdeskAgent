# Knowledge processing and publication operations

Milestone 6, Task 6.3 turns acquired originals into versioned, validated chunks and embeddings. It
does not provide retrieval APIs. Content remains unsearchable until a human-authorized publication
operation selects an exact processing version.

## Runtime configuration

The worker reads originals from the private object store configured for acquisition. Configure a
production embedding provider with an approved HTTPS endpoint, secret API key, model code, expected
dimension, timeout, and batch size. The deterministic provider is limited to development and tests
and is rejected in production. Parser, chunker, chunk configuration, and embedding-model identity
are persisted with each processing version.

Normalized text is stored under the source document version in private object storage. Document
bytes, extracted text, embedding credentials, and provider response bodies must not be logged.

## Processing and retry

The worker claims only acquisition-complete items and rechecks source and manifest versions and
permissions before processing. Parsing failures, empty extraction, and validation failures fail
closed. Transient embedding or storage failures use bounded exponential retry. Multiple workers may
run concurrently; row locking allows only one worker to claim an item, and an advisory lock prevents
duplicate processing identities.

Changing a parser version, chunker implementation/version, chunk configuration, or embedding model
creates a new immutable processing version. Reprocessing never changes the processing version pinned
to a published document. Inspect `kb.document_processing_version`, `kb.document_chunk`,
`kb.chunk_embedding_1536`, `kb.ingestion_run_item`, and append-only `kb.ingestion_event` records when
investigating failures.

## Publication and retirement

Only a knowledge approver or platform administrator may approve, publish, or retire a document. The
source owner cannot approve their own document. Publication requires an active human-approved
document, a completed processing version with a passing or reviewed-warning validation result,
complete embeddings, intact document/source/audience/security lineage, and a fresh source permission
check.

Publication atomically pins the selected processing version and writes an immutable
`kb.document_publication_event` containing the parser, chunker, embedding model, validation, source
permission, ACL, and actor evidence. The active-chunk view exposes only that pinned version. A newer
processing version therefore remains invisible until separately reviewed and published. Retirement
removes all versions of the document from the active view and records immutable retirement evidence.

If authorization or source rights become uncertain, retire the document and disable or reject its
source. Do not edit publication evidence, chunks, or embeddings directly; correct the source or
configuration, create a new processing version, review it, and publish that version.
