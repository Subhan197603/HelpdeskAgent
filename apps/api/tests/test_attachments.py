"""Security-focused unit tests for attachment validation and scanner responses."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from apps.api.app.attachments.clamav import ClamAVScanner, ScannerError
from apps.api.app.attachments.models import Attachment
from apps.api.app.attachments.schemas import UploadRequest
from apps.api.app.attachments.service import _detect_mime, _validate_content
from apps.api.app.core.exceptions import UnsupportedFileError


def _attachment(content: bytes, filename: str = "evidence.txt") -> Attachment:
    return Attachment(
        UUID("41000000-0000-0000-0000-000000000001"),
        UUID("20000000-0000-0000-0000-000000000001"),
        UUID("40000000-0000-0000-0000-000000000001"),
        "ERP-1",
        UUID("22000000-0000-0000-0000-000000000001"),
        filename,
        "quarantine/generated",
        None,
        "text/plain",
        None,
        len(content),
        hashlib.sha256(content).hexdigest(),
        "PENDING",
        "QUARANTINED",
        "PUBLIC",
        None,
        None,
        None,
        0,
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_upload_contract_rejects_paths_and_non_hex_checksum() -> None:
    with pytest.raises(ValueError):
        UploadRequest(
            filename="../payload.txt",
            content_type="text/plain",
            file_size_bytes=4,
            sha256_checksum="not-a-checksum",
        )


def test_detected_signature_size_and_checksum_are_authoritative() -> None:
    content = b"safe evidence\n"
    attachment = _attachment(content)
    assert _detect_mime(content) == "text/plain"
    _validate_content(attachment, content, "text/plain")
    with pytest.raises(UnsupportedFileError):
        _validate_content(
            replace(attachment, original_filename="evidence.pdf"), content, "text/plain"
        )
    with pytest.raises(UnsupportedFileError):
        _validate_content(attachment, content + b"changed", "text/plain")


def test_binary_unknown_file_fails_closed() -> None:
    content = b"MZ\x00\x01binary"
    assert _detect_mime(content) == "application/octet-stream"
    with pytest.raises(UnsupportedFileError):
        _validate_content(_attachment(content), content, "application/octet-stream")


def test_clamav_parser_handles_infected_fixture_without_writing_it_to_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Construct the standard antivirus test signature only in memory so source checkout and
    # developer antivirus tooling do not mistake a persisted fixture for a live artifact.
    test_signature = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    scanner = object.__new__(ClamAVScanner)
    scanner._timeout = 1.0

    async def command(_: bytes) -> str:
        return "ClamAV 1.4.3/12345/Sun Aug 2 00:00:00 2026"

    async def instream(content: bytes) -> str:
        assert content == test_signature
        return "stream: Win.Test.EICAR_HDB-1 FOUND"

    monkeypatch.setattr(scanner, "_command", command)
    monkeypatch.setattr(scanner, "_instream", instream)
    result = asyncio.run(scanner.scan(test_signature))
    assert not result.clean
    assert result.engine == "ClamAV"
    assert result.threat_name == "Win.Test.EICAR_HDB-1"


def test_clamav_invalid_response_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = object.__new__(ClamAVScanner)
    scanner._timeout = 1.0

    async def command(_: bytes) -> str:
        return "ClamAV test"

    async def instream(_: bytes) -> str:
        return "unexpected"

    monkeypatch.setattr(scanner, "_command", command)
    monkeypatch.setattr(scanner, "_instream", instream)
    with pytest.raises(ScannerError):
        asyncio.run(scanner.scan(b"safe"))
