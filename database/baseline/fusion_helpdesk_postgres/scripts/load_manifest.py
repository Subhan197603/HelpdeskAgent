#!/usr/bin/env python3
"""Load or update controlled knowledge-manifest entries in PostgreSQL."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

import psycopg

ALLOWED_PERMISSIONS = {"PENDING", "APPROVED", "REJECTED", "NOT_REQUIRED"}
ALLOWED_METHODS = {
    "MANUAL_UPLOAD",
    "APPROVED_DIRECT_DOWNLOAD",
    "API_FEED",
    "REPOSITORY_CONNECTOR",
    "TICKET_PUBLICATION",
}


def blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def resolve_tenant_id(cur: psycopg.Cursor[Any], tenant_code: str | None) -> str | None:
    if not tenant_code:
        return None
    cur.execute(
        "SELECT tenant_id FROM identity.tenant WHERE tenant_code = %s",
        (tenant_code,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown tenant code: {tenant_code}")
    return str(row[0])


def resolve_source_id(
    cur: psycopg.Cursor[Any], source_code: str, tenant_id: str | None
) -> str:
    cur.execute(
        """
        SELECT source_id
          FROM kb.source
         WHERE source_code = %s
           AND (tenant_id = %s::uuid OR (tenant_id IS NULL AND %s::uuid IS NULL))
        """,
        (source_code, tenant_id, tenant_id),
    )
    row = cur.fetchone()
    if not row and tenant_id:
        cur.execute(
            "SELECT source_id FROM kb.source WHERE source_code = %s AND tenant_id IS NULL",
            (source_code,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown source code: {source_code}")
    return str(row[0])


def resolve_release_id(
    cur: psycopg.Cursor[Any], family: str | None, code: str | None
) -> str | None:
    if not family or not code or family == "COMPANY_DOCUMENT" and code == "CURRENT":
        return None
    cur.execute(
        "SELECT release_id FROM kb.release WHERE release_family = %s AND release_code = %s",
        (family, code),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown release: {family}/{code}")
    return str(row[0])


def resolve_product_id(cur: psycopg.Cursor[Any], product_code: str | None) -> str | None:
    if not product_code:
        return None
    cur.execute(
        "SELECT product_node_id FROM kb.product_node WHERE product_code = %s AND tenant_id IS NULL",
        (product_code,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown product code: {product_code}")
    return str(row[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--tenant-code")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dsn:
        raise SystemExit("Provide --dsn or set DATABASE_URL")

    loaded = 0
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur, args.csv_file.open(encoding="utf-8-sig", newline="") as handle:
            tenant_id = resolve_tenant_id(cur, args.tenant_code)
            for line_no, row in enumerate(csv.DictReader(handle), start=2):
                try:
                    permission = row["acquisition_permission"].strip().upper()
                    method = row["acquisition_method"].strip().upper()
                    if permission not in ALLOWED_PERMISSIONS:
                        raise ValueError(f"Invalid acquisition_permission: {permission}")
                    if method not in ALLOWED_METHODS:
                        raise ValueError(f"Invalid acquisition_method: {method}")

                    source_id = resolve_source_id(cur, row["source_code"].strip(), tenant_id)
                    release_id = resolve_release_id(
                        cur,
                        blank_to_none(row.get("release_family")),
                        blank_to_none(row.get("release_code")),
                    )
                    product_id = resolve_product_id(cur, blank_to_none(row.get("product_code")))

                    values = (
                        tenant_id,
                        source_id,
                        release_id,
                        product_id,
                        row["manifest_key"].strip(),
                        row["document_title"].strip(),
                        row["document_type"].strip().upper(),
                        row["audience_code"].strip().upper(),
                        blank_to_none(row.get("canonical_url")),
                        blank_to_none(row.get("pdf_url")),
                        blank_to_none(row.get("html_url")),
                        blank_to_none(row.get("local_file_path")),
                        row["target_collection"].strip(),
                        row["security_classification"].strip().upper(),
                        permission,
                        blank_to_none(row.get("permission_reference")),
                        method,
                        parse_bool(row.get("enabled_flag")),
                        blank_to_none(row.get("expected_sha256")),
                        blank_to_none(row.get("notes")),
                    )

                    cur.execute(
                        """
                        INSERT INTO kb.ingestion_manifest_entry(
                            tenant_id, source_id, release_id, product_node_id,
                            manifest_key, document_title, document_type, audience_code,
                            canonical_url, pdf_url, html_url, local_file_path,
                            target_collection, security_classification,
                            acquisition_permission, permission_reference,
                            acquisition_method, enabled_flag, expected_sha256, notes
                        ) VALUES (
                            %s::uuid,%s::uuid,%s::uuid,%s::uuid,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        ON CONFLICT (source_id, manifest_key)
                        DO UPDATE SET
                            tenant_id = EXCLUDED.tenant_id,
                            release_id = EXCLUDED.release_id,
                            product_node_id = EXCLUDED.product_node_id,
                            document_title = EXCLUDED.document_title,
                            document_type = EXCLUDED.document_type,
                            audience_code = EXCLUDED.audience_code,
                            canonical_url = EXCLUDED.canonical_url,
                            pdf_url = EXCLUDED.pdf_url,
                            html_url = EXCLUDED.html_url,
                            local_file_path = EXCLUDED.local_file_path,
                            target_collection = EXCLUDED.target_collection,
                            security_classification = EXCLUDED.security_classification,
                            acquisition_permission = EXCLUDED.acquisition_permission,
                            permission_reference = EXCLUDED.permission_reference,
                            acquisition_method = EXCLUDED.acquisition_method,
                            enabled_flag = EXCLUDED.enabled_flag,
                            expected_sha256 = EXCLUDED.expected_sha256,
                            notes = EXCLUDED.notes,
                            updated_at = now()
                        """,
                        values,
                    )
                    loaded += 1
                except Exception as exc:
                    raise RuntimeError(f"Manifest line {line_no}: {exc}") from exc

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

    action = "validated" if args.dry_run else "loaded"
    print(f"{action} {loaded} manifest entries")


if __name__ == "__main__":
    main()
