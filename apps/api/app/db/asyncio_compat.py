"""Cross-platform entry point for asynchronous command-line operations."""

import asyncio
import sys
from collections.abc import Coroutine


def run_async[T](coroutine: Coroutine[object, object, T]) -> T:
    if sys.platform == "win32":
        return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coroutine)
