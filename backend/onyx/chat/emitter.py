import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from queue import Queue

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet

_packet_sink: ContextVar[Callable[[Packet], None] | None] = ContextVar(
    "tool_packet_sink", default=None
)


@contextmanager
def capture_tool_packets(sink: Callable[[Packet], None]) -> Iterator[None]:
    parent = _packet_sink.get()

    def publish(packet: Packet) -> None:
        token = _packet_sink.set(parent)
        try:
            sink(packet)
        finally:
            _packet_sink.reset(token)

    token = _packet_sink.set(publish)
    try:
        yield
    finally:
        _packet_sink.reset(token)


class ModelStreamStatus(str, Enum):
    DONE = "done"


class Emitter:
    """Tag packets with their model index and send them to the chat coordinator."""

    def __init__(
        self,
        merged_queue: Queue[tuple[int, Packet | ModelStreamStatus]],
        model_idx: int = 0,
        drain_done: threading.Event | None = None,
    ) -> None:
        self._model_idx = model_idx
        self._merged_queue = merged_queue
        self._drain_done = drain_done

    def emit(self, packet: Packet) -> None:
        sink = _packet_sink.get()
        if sink is not None:
            sink(packet)
            return
        if self._drain_done is not None and self._drain_done.is_set():
            return
        base = packet.placement or Placement(turn_index=0)
        tagged = Packet(
            placement=base.model_copy(update={"model_index": self._model_idx}),
            obj=packet.obj,
        )
        self._merged_queue.put((self._model_idx, tagged))


class NullEmitter(Emitter):
    """Emitter that silently discards all packets.

    Used by callers that run tools outside the chat streaming context
    (e.g. the Search API, MCP server).
    """

    def __init__(self) -> None:
        self._model_idx = 0
        self._merged_queue = None
        self._drain_done = None

    def emit(self, packet: Packet) -> None:
        pass
