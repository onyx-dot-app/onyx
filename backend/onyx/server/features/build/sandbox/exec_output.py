"""Output shaping for `HarnessSandbox` exec calls: a byte cap per call (head
and tail) and a token cap for the model (head and tail)."""

import codecs

from onyx.microvm.models import OutputStream
from onyx.server.features.build.sandbox.harness_base import EXEC_CALL_OUTPUT_MAX_BYTES

# Token estimate for the cap, as Codex does.
BYTES_PER_TOKEN = 4


def _omitted_marker(count: int, unit: str) -> str:
    return f"\n[... {count} {unit} omitted ...]\n"


class ExecOutputBuffer:
    """Collects one call's output. Keeps the first and last half of
    `max_bytes`; `add` returns the text to stream now (the head only)."""

    def __init__(self, max_bytes: int = EXEC_CALL_OUTPUT_MAX_BYTES) -> None:
        self._head_budget = max_bytes // 2
        self._tail_budget = max_bytes - self._head_budget
        self._head = bytearray()
        self._tail = bytearray()
        self._dropped = 0
        self.total_bytes = 0
        self._decoders = {
            stream: codecs.getincrementaldecoder("utf-8")(errors="replace")
            for stream in OutputStream
        }

    def add(self, stream: OutputStream, data: bytes) -> str:
        """Add bytes of one stream. Returns the decoded part that went into
        the head (empty once the head is full)."""
        self.total_bytes += len(data)
        room = self._head_budget - len(self._head)
        head_part = data[: max(room, 0)]
        self._head += head_part
        rest = data[len(head_part) :]
        if rest:
            self._tail += rest
            over = len(self._tail) - self._tail_budget
            if over > 0:
                del self._tail[:over]
                self._dropped += over
        return self._decoders[stream].decode(head_part) if head_part else ""

    def add_gap(self, stream: OutputStream, count: int) -> str:
        """The daemon dropped `count` bytes of a stream before we read them."""
        marker = f"\n[... {count} bytes of {stream.value.lower()} lost ...]\n"
        return self.add(stream, marker.encode())

    @property
    def truncated(self) -> bool:
        return self._dropped > 0

    def text(self) -> str:
        if not self._dropped:
            # Nothing cut: decode as one, so a character split between the
            # head and the tail stays whole.
            return (self._head + self._tail).decode("utf-8", errors="replace")
        head = self._head.decode("utf-8", errors="replace")
        tail = self._tail.decode("utf-8", errors="replace")
        return head + _omitted_marker(self._dropped, "bytes") + tail


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
