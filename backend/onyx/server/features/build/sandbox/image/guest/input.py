"""Finite guest input without closing the attached CRI stdin stream."""

import signal
from collections.abc import Iterator
from typing import BinaryIO

MAX_FRAME_BYTES = 64 * 1024


def _drain_timeout(_signum: int, _frame: object) -> None:
    raise TimeoutError("guest input drain timed out")


class FramedInput:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self._complete = False
        self._broken = False
        self._transferred = False
        self._drain_remaining: int | None = None

    def _read(self, size: int) -> bytes:
        if self._drain_remaining is not None:
            if self._drain_remaining <= 0:
                raise ValueError("guest input drain exceeds byte limit")
            size = min(size, self._drain_remaining)
        chunk = self.source.read(size)
        if not isinstance(chunk, bytes) or len(chunk) > size:
            raise ValueError("guest input must return bounded bytes")
        if self._drain_remaining is not None:
            self._drain_remaining -= len(chunk)
        return chunk

    def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        try:
            while len(data) < size:
                chunk = self._read(size - len(data))
                if not chunk:
                    raise ValueError("truncated guest input frame")
                data.extend(chunk)
        except BaseException:
            # A failed read can consume bytes without returning them.
            self._broken = True
            raise
        return bytes(data)

    def chunks(self, *, max_bytes: int) -> Iterator[bytes]:
        if self._transferred:
            raise RuntimeError("guest input belongs to the restore child")
        if self._broken:
            raise ValueError("guest input framing is already invalid")
        total = 0
        while not self._complete:
            self._broken = True
            size = int.from_bytes(self._read_exact(4), "big")
            if size > MAX_FRAME_BYTES:
                raise ValueError("guest input frame exceeds 64 KiB limit")
            if size == 0:
                self._complete = True
                self._broken = False
                return
            chunk = self._read_exact(size)
            self._broken = False
            total += size
            if total > max_bytes:
                raise ValueError(f"input exceeds {max_bytes} byte limit")
            yield chunk

    def require_empty(self) -> None:
        for _chunk in self.chunks(max_bytes=0):
            pass

    def transfer(self) -> None:
        self._transferred = True

    def drain_after_error(
        self,
        *,
        max_bytes: int = 512 * 1024 * 1024,
        timeout_seconds: float = 5,
    ) -> None:
        if self._complete or self._transferred:
            return
        previous_handler = signal.signal(signal.SIGALRM, _drain_timeout)
        self._drain_remaining = max_bytes
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        try:
            if not self._broken:
                try:
                    for _chunk in self.chunks(max_bytes=max_bytes):
                        pass
                except TimeoutError:
                    return
                except Exception:
                    pass
            if self._broken:
                while self._read(MAX_FRAME_BYTES):
                    pass
        except Exception:
            pass
        finally:
            self._drain_remaining = None
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
