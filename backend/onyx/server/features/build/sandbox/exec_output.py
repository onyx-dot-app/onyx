"""The limits of `HarnessSandbox` exec calls, and their output: a byte cap
per call that keeps the head and the tail."""

import codecs
import time
from collections import deque

from onyx.microvm.models import OutputStream

EXEC_CALL_OUTPUT_MAX_BYTES = 1 << 20
EXEC_DEFAULT_YIELD_MS = 10_000
EXEC_MIN_YIELD_MS = 250
EXEC_MAX_YIELD_MS = 30_000
WRITE_STDIN_DEFAULT_YIELD_MS = 250
WRITE_STDIN_MAX_YIELD_MS = 30_000
# An empty write_stdin (a poll) waits at least this long for new output.
POLL_MIN_YIELD_MS = 5_000
POLL_MAX_YIELD_MS = 300_000


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _utf8_prefix(text: str, max_bytes: int) -> str:
    """The longest prefix of whole characters within max_bytes."""
    return text.encode("utf-8")[: max(max_bytes, 0)].decode("utf-8", errors="ignore")


class ExecOutputBuffer:
    """One exec_command or write_stdin call: its output, and the session ID
    of its command while the command's record stays.

    Each stream is decoded on its own (a character never mixes bytes of
    stdout and stderr). Keeps the first and last half of `max_bytes` (UTF-8)
    and counts the characters between them; `add` returns the text to stream
    now, the part that went into the head. The result's output replaces
    what streamed."""

    def __init__(self, max_bytes: int = EXEC_CALL_OUTPUT_MAX_BYTES) -> None:
        self.started_at = time.monotonic()
        # Set while the command's record stays.
        self.session_id: str | None = None
        self._head_budget = max_bytes // 2
        self._tail_budget = max_bytes - self._head_budget
        self._head: list[str] = []
        self._head_bytes = 0
        self._tail: deque[str] = deque()
        self._tail_bytes = 0
        self._dropped_chars = 0
        self._lost = False
        self.total_bytes = 0
        self._decoders = {
            stream: codecs.getincrementaldecoder("utf-8")(errors="replace")
            for stream in OutputStream
        }

    def add(self, stream: OutputStream, data: bytes) -> str:
        """Add bytes of one stream. Returns the decoded part that went into
        the head (empty once the head is full)."""
        self.total_bytes += len(data)
        return self._add_text(self._decoders[stream].decode(data))

    def add_gap(self, stream: OutputStream, count: int) -> str:
        """The daemon dropped `count` bytes of a stream before we read them.
        Bytes on each side of the gap are not one character: flush the
        decoder and start a new one."""
        self._lost = True
        pending = self._add_text(self._decoders[stream].decode(b"", final=True))
        self._decoders[stream] = codecs.getincrementaldecoder("utf-8")(errors="replace")
        return pending + self._add_text(
            f"\n[... {count} bytes of {stream.value.lower()} lost ...]\n"
        )

    def _add_text(self, text: str) -> str:
        if not text:
            return ""
        head_part = ""
        if not self._tail:
            head_part = _utf8_prefix(text, self._head_budget - self._head_bytes)
            self._head.append(head_part)
            self._head_bytes += _utf8_len(head_part)
        rest = text[len(head_part) :]
        if rest:
            self._tail.append(rest)
            self._tail_bytes += _utf8_len(rest)
            self._trim_tail()
        return head_part

    def _trim_tail(self) -> None:
        while self._tail_bytes > self._tail_budget:
            first = self._tail[0]
            size = _utf8_len(first)
            over = self._tail_bytes - self._tail_budget
            if size <= over:
                self._tail.popleft()
                self._tail_bytes -= size
                self._dropped_chars += len(first)
                continue
            kept = first.encode("utf-8")[over:].decode("utf-8", errors="ignore")
            self._tail[0] = kept
            self._tail_bytes -= size - _utf8_len(kept)
            self._dropped_chars += len(first) - len(kept)

    def pending_bytes(self, stream: OutputStream) -> int:
        """Bytes of an incomplete character that the stream's decoder holds."""
        return len(self._decoders[stream].getstate()[0])

    def finish(self) -> str:
        """The command ended: flush the bytes of an incomplete character.
        Returns the part to stream, as `add` does."""
        return "".join(
            self._add_text(decoder.decode(b"", final=True))
            for decoder in self._decoders.values()
        )

    @property
    def truncated(self) -> bool:
        """The byte cap dropped output, or the daemon lost some."""
        return self._dropped_chars > 0 or self._lost

    @property
    def omitted_chars(self) -> int:
        """Characters between the head and the tail that the byte cap dropped."""
        return self._dropped_chars

    @property
    def head(self) -> str:
        return "".join(self._head)

    @property
    def tail(self) -> str:
        return "".join(self._tail)
