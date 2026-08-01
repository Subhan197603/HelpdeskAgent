#!/usr/bin/env python3
"""Register approved local files as versioned knowledge documents."""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any

import psycopg


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--tenant-code")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if not args.dsn:
        raise SystemExit("Provide --dsn or set DATABASE_URL")

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        tenant_id: Any = None
        if args.tenant_code:
            cur.execute(
                "SELECT tenant_id FROM identity.tenant WHERE tenant_code=%s",
                (args.tenant_code,),
            )
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"Unknown tenant code: {args.tenant_code}")
            tenant_id = row[0]

        cur.execute(
            """
            SELECT m.manifest_entry_id, m.tenant_id, m.source_id, m.release_id,
                   m.product_node_id, m.manifest_key, m.document_title,
                   m.document_type, m.audience_code, m.canonical_url,
                   m.local_file_path, m.security_classification,
                   m.permission_reference, m.expected_sha256
              FROM kb.ingestion_manifest_entry m
             WHERE m.enabled_flag
               AND m.acquisition_method = 'MANUAL_UPLOAD'
               AND m.acquisition_permission IN ('APPROVED','NOT_REQUIRED')
               AND m.local_file_path IS NOT NULL
               AND (%s::uuid IS NULL OR m.tenant_id = %s::uuid)
             ORDER BY m.manifest_key
             LIMIT %s
            """,
            (tenant_id, tenant_id, args.limit),
        )
        entries = cur.fetchall()

        cur.execute(
            """
            INSERT INTO kb.ingestion_run(
                tenant_id, run_type, run_status, started_at, worker_name, total_items
            ) VALUES (%s,'ACQUISITION','RUNNING',now(),%s,%s)
            RETURNING ingestion_run_id
            """,
            (tenant_id, "register_local_documents.py", len(entries)),
        )
        run_id = cur.fetchone()[0]
        conn.commit()

        completed = failed = skipped = 0
        for entry in entries:
            (
                manifest_id, entry_tenant_id, source_id, release_id, product_id,
                manifest_key, title, document_type, audience, canonical_url,
                local_path, security_classification, permission_reference,
                expected_sha256,
            ) = entry
            path = Path(local_path)
            try:
                if not path.is_file():
                    raise FileNotFoundError(path)
                observed = checksum(path)
                if expected_sha256 and observed.lower() != expected_sha256.lower():
                    raise ValueError("SHA-256 does not match the manifest")

                cur.execute(
                    """
                    SELECT d.document_id, dv.document_version_id
                      FROM kb.document d
                      JOIN kb.document_version dv ON dv.document_id=d.document_id
                     WHERE d.source_id=%s AND d.external_document_key=%s
                       AND dv.sha256_checksum=%s
                     LIMIT 1
                    """,
                    (source_id, manifest_key, observed),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """
                        INSERT INTO kb.ingestion_run_item(
                            ingestion_run_id, manifest_entry_id, item_status,
                            document_id, document_version_id, attempt_count,
                            started_at, completed_at, downloaded_uri, observed_sha256
                        ) VALUES (%s,%s,'SKIPPED_UNCHANGED',%s,%s,1,now(),now(),%s,%s)
                        """,
                        (run_id, manifest_id, existing[0], existing[1], str(path.resolve()), observed),
                    )
                    skipped += 1
                    conn.commit()
                    continue

                cur.execute(
                    """
                    INSERT INTO kb.document(
                        tenant_id, source_id, product_node_id, release_id,
                        external_document_key, document_title, document_type,
                        audience_code, canonical_url, security_classification,
                        approval_status, effective_from
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'UNDER_REVIEW',CURRENT_DATE
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING document_id
                    """,
                    (
                        entry_tenant_id, source_id, product_id, release_id,
                        manifest_key, title, document_type, audience,
                        canonical_url, security_classification,
                    ),
                )
                row = cur.fetchone()
                if row:
                    document_id = row[0]
                else:
                    cur.execute(
                        "SELECT document_id FROM kb.document WHERE source_id=%s AND external_document_key=%s",
                        (source_id, manifest_key),
                    )
                    document_id = cur.fetchone()[0]

                cur.execute(
                    "SELECT COALESCE(MAX(version_number),0)+1 FROM kb.document_version WHERE document_id=%s",
                    (document_id,),
                )
                version_no = cur.fetchone()[0]
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

                cur.execute(
                    "UPDATE kb.document_version SET current_version_flag=false WHERE document_id=%s",
                    (document_id,),
                )
                cur.execute(
                    """
                    INSERT INTO kb.document_version(
                        document_id, version_number, original_file_uri,
                        content_type, file_size_bytes, sha256_checksum,
                        acquired_at, acquisition_run_id, copyright_notice,
                        extraction_status, validation_status, current_version_flag
                    ) VALUES (%s,%s,%s,%s,%s,%s,now(),%s,%s,'PENDING','PENDING',true)
                    RETURNING document_version_id
                    """,
                    (
                        document_id, version_no, str(path.resolve()), content_type,
                        path.stat().st_size, observed, run_id,
                        permission_reference,
                    ),
                )
                version_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO kb.ingestion_run_item(
                        ingestion_run_id, manifest_entry_id, item_status,
                        document_id, document_version_id, attempt_count,
                        started_at, completed_at, downloaded_uri, observed_sha256
                    ) VALUES (%s,%s,'ACQUIRED',%s,%s,1,now(),now(),%s,%s)
                    """,
                    (run_id, manifest_id, document_id, version_id, str(path.resolve()), observed),
                )
                completed += 1
                conn.commit()
            except Exception as exc:
                failed += 1
                cur.execute(
                    """
                    INSERT INTO kb.ingestion_run_item(
                        ingestion_run_id, manifest_entry_id, item_status,
                        attempt_count, started_at, completed_at, error_code, error_message
                    ) VALUES (%s,%s,'FAILED',1,now(),now(),%s,%s)
                    ON CONFLICT (ingestion_run_id, manifest_entry_id)
                    DO UPDATE SET item_status='FAILED', completed_at=now(),
                                  error_code=EXCLUDED.error_code,
                                  error_message=EXCLUDED.error_message
                    """,
                    (run_id, manifest_id, exc.__class__.__name__, str(exc)[:4000]),
                )
                conn.commit()

        status = "COMPLETED" if failed == 0 else "COMPLETED_WITH_ERRORS"
        cur.execute(
            """
            UPDATE kb.ingestion_run
               SET run_status=%s, completed_at=now(), completed_items=%s,
                   failed_items=%s,
                   error_summary=%s
             WHERE ingestion_run_id=%s
            """,
            (status, completed + skipped, failed, f"Skipped unchanged: {skipped}", run_id),
        )
        conn.commit()

    print(f"Registration run {run_id}: {completed} new, {skipped} unchanged, {failed} failed")


if __name__ == "__main__":
    main()
