"""Bounded ClamAV INSTREAM protocol adapter."""

import asyncio
import re
import struct
from dataclasses import dataclass
from typing import Protocol

from apps.api.app.core.settings import Settings

_FOUND = re.compile(r"^stream: (.+) FOUND$")


class ScannerError(Exception):
    """Scanner was unavailable, timed out, or returned an invalid response."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    engine: str
    version: str
    threat_name: str | None = None


class MalwareScanner(Protocol):
    async def scan(self, content: bytes) -> ScanResult: ...


class ClamAVScanner:
    def __init__(self, settings: Settings) -> None:
        self._host = settings.clamav_host
        self._port = settings.clamav_port
        self._timeout = settings.clamav_timeout_seconds

    async def scan(self, content: bytes) -> ScanResult:
        try:
            version = await asyncio.wait_for(self._command(b"zVERSION\0"), self._timeout)
            response = await asyncio.wait_for(self._instream(content), self._timeout)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ScannerError("Malware scanner unavailable") from exc
        match = _FOUND.fullmatch(response)
        if response == "stream: OK":
            return ScanResult(True, "ClamAV", version)
        if match:
            return ScanResult(False, "ClamAV", version, match.group(1))
        raise ScannerError("Malware scanner returned an invalid response")

    async def _command(self, command: bytes) -> str:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(command)
            await writer.drain()
            return (await reader.readuntil(b"\0")).rstrip(b"\0").decode("utf-8", "replace")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _instream(self, content: bytes) -> str:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(b"zINSTREAM\0")
            for offset in range(0, len(content), 64 * 1024):
                chunk = content[offset : offset + 64 * 1024]
                writer.write(struct.pack("!I", len(chunk)))
                writer.write(chunk)
            writer.write(struct.pack("!I", 0))
            await writer.drain()
            return (await reader.readuntil(b"\0")).rstrip(b"\0").decode("utf-8", "replace")
        finally:
            writer.close()
            await writer.wait_closed()
