#!/usr/bin/env python3
"""
Download only explicit, approved manifest URLs.

This script does not crawl sites or discover links. Oracle-hosted downloads are
blocked unless both the manifest entry and command line contain a permission
reference. Retain legal approval records outside this script as well.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import requests

ORACLE_DOMAINS = {"docs.oracle.com", "www.oracle.com", "oracle.com"}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def choose_url(pdf_url: str | None, html_url: str | None, canonical_url: str | None) -> str:
    for value in (pdf_url, html_url, canonical_url):
        if value:
            return value
    raise ValueError("No acquisition URL is present")


def filename_for(key: str, url: str, content_type: str | None) -> str:
    suffix = Path(urlparse(url).path).suffix
    if not suffix:
        suffix = ".pdf" if content_type and "pdf" in content_type.lower() else ".html"
    return SAFE_NAME.sub("_", key).strip("_") + suffix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--oracle-permission-reference")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--user-agent", default="CompanyKnowledgeIngestion/1.0")
    args = parser.parse_args()

    if not args.dsn:
        raise SystemExit("Provide --dsn or set DATABASE_URL")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.manifest_entry_id, m.manifest_key, m.pdf_url, m.html_url,
                   m.canonical_url, m.permission_reference, s.publisher_name
              FROM kb.ingestion_manifest_entry m
              JOIN kb.source s ON s.source_id = m.source_id
             WHERE m.enabled_flag
               AND m.acquisition_permission = 'APPROVED'
               AND m.acquisition_method = 'APPROVED_DIRECT_DOWNLOAD'
             ORDER BY m.manifest_key
             LIMIT %s
            """,
            (args.limit,),
        )
        entries = cur.fetchall()

        cur.execute(
            """
            INSERT INTO kb.ingestion_run(run_type, run_status, started_at, worker_name, total_items)
            VALUES ('ACQUISITION','RUNNING',now(),%s,%s)
            RETURNING ingestion_run_id
            """,
            ("acquire_approved_documents.py", len(entries)),
        )
        run_id = cur.fetchone()[0]
        conn.commit()

        completed = failed = 0
        session = requests.Session()
        session.headers["User-Agent"] = args.user_agent

        for entry in entries:
            entry_id, key, pdf_url, html_url, canonical_url, permission_ref, _publisher = entry
            try:
                url = choose_url(pdf_url, html_url, canonical_url)
                domain = (urlparse(url).hostname or "").lower()
                if domain in ORACLE_DOMAINS:
                    if not permission_ref or not args.oracle_permission_reference:
                        raise PermissionError(
                            "Oracle URL blocked: record and command-line permission references are required"
                        )

                cur.execute(
                    """
                    INSERT INTO kb.ingestion_run_item(
                        ingestion_run_id, manifest_entry_id, item_status,
                        attempt_count, started_at
                    ) VALUES (%s,%s,'ACQUIRING',1,now())
                    RETURNING ingestion_run_item_id
                    """,
                    (run_id, entry_id),
                )
                item_id = cur.fetchone()[0]
                conn.commit()

                response = session.get(url, timeout=(15, 120), allow_redirects=True)
                response.raise_for_status()
                payload = response.content
                digest = hashlib.sha256(payload).hexdigest()
                name = filename_for(key, response.url, response.headers.get("Content-Type"))
                destination = args.output_dir / name
                destination.write_bytes(payload)

                cur.execute(
                    """
                    UPDATE kb.ingestion_run_item
                       SET item_status = 'ACQUIRED', completed_at = now(),
                           downloaded_uri = %s, observed_sha256 = %s
                     WHERE ingestion_run_item_id = %s
                    """,
                    (str(destination.resolve()), digest, item_id),
                )
                completed += 1
                conn.commit()
                time.sleep(max(0.0, args.delay_seconds))
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
                    (run_id, entry_id, exc.__class__.__name__, str(exc)[:4000]),
                )
                conn.commit()

        status = "COMPLETED" if failed == 0 else "COMPLETED_WITH_ERRORS"
        cur.execute(
            """
            UPDATE kb.ingestion_run
               SET run_status=%s, completed_at=now(), completed_items=%s,
                   failed_items=%s
             WHERE ingestion_run_id=%s
            """,
            (status, completed, failed, run_id),
        )
        conn.commit()

    print(f"Acquisition run {run_id}: {completed} completed, {failed} failed")


if __name__ == "__main__":
    main()
