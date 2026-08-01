"""Optional ClamAV daemon health adapter."""

import asyncio


class ClamAVHealthProbe:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    async def check(self) -> bool:
        writer: asyncio.StreamWriter | None = None
        try:
            reader, connected_writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=2.0
            )
            writer = connected_writer
            writer.write(b"zPING\0")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(16), timeout=2.0)
            return b"PONG" in response
        except (OSError, TimeoutError):
            return False
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def close(self) -> None:
        return None
