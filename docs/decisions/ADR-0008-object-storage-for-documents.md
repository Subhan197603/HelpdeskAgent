# ADR-0008: Object storage for documents

- Status: Accepted
- Date: 2026-08-01

## Context

Documents and attachments need scalable storage, quarantine, retention, and controlled downloads.

## Decision

Store file bodies in private S3-compatible object storage and metadata in PostgreSQL.

## Alternatives

Database byte storage and public filesystem paths were rejected.

## Consequences

Every access requires authorization and short-lived URLs; local development uses MinIO.
