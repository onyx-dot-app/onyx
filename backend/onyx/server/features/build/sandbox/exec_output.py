"""Output shaping for `HarnessSandbox` exec calls: a byte cap per call (head
and tail) and a token cap for the model (head and tail)."""

import codecs
from collections import deque

from onyx.microvm.models import OutputStream
from onyx.server.features.build.sandbox.harness_base import EXEC_CALL_OUTPUT_MAX_BYTES

# Token estimate for the cap, as Codex does.
BYTES_PER_TOKEN = 4


def _omitted_marker(count: int, unit: str) -> str:
    return f"\n[... {count} {unit} omitted ...]\n"


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _utf8_prefix(text: str, max_bytes: int) -> str:
    """The longest prefix of whole characters within max_bytes."""
    return text.encode("utf-8")[: max(max_bytes, 0)].decode("utf-8", errors="ignore")


class ExecOutputBuffer:
    """Collects one call's output. Each stream is decoded on its own (a
    character never mixes bytes of stdout and stderr). Keeps the first and
    last half of `max_bytes` (UTF-8); `add` returns the text to stream now
    (the head only)."""

    def __init__(self, max_bytes: int = EXEC_CALL_OUTPUT_MAX_BYTES) -> None:
        self._head_budget = max_bytes // 2
        self._tail_budget = max_bytes - self._head_budget
        self._head: list[str] = []
        self._head_bytes = 0
        self._tail: deque[str] = deque()
        self._tail_bytes = 0
        self._dropped = 0
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
                self._dropped += size
                continue
            kept = first.encode("utf-8")[over:].decode("utf-8", errors="ignore")
            removed = size - _utf8_len(kept)
            self._tail[0] = kept
            self._tail_bytes -= removed
            self._dropped += removed

    def finish(self) -> str:
        """The command ended: flush the bytes of an incomplete character.
        Returns the part to stream, as `add` does."""
        return "".join(
            self._add_text(decoder.decode(b"", final=True))
            for decoder in self._decoders.values()
        )

    @property
    def truncated(self) -> bool:
        return self._dropped > 0 or self._lost

    def text(self) -> str:
        head = "".join(self._head)
        tail = "".join(self._tail)
        if self._dropped:
            return head + _omitted_marker(self._dropped, "bytes") + tail
        return head + tail


def estimate_tokens(text: str) -> int:
    return (len(text.encode("utf-8")) + BYTES_PER_TOKEN - 1) // BYTES_PER_TOKEN


def cut_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    """Keep the head and tail of `text` within about `max_tokens`. Returns
    the text and whether it was cut."""
    max_bytes = max(max_tokens, 1) * BYTES_PER_TOKEN
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text, False
    half = max_bytes // 2
    head = data[:half].decode("utf-8", errors="ignore")
    tail = data[len(data) - half :].decode("utf-8", errors="ignore")
    omitted = estimate_tokens(text) - estimate_tokens(head) - estimate_tokens(tail)
    return head + _omitted_marker(max(omitted, 1), "tokens") + tail, True
