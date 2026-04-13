import threading
from queue import Queue

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet


class Emitter:
    """Routes packets from LLM/tool execution to the ``_run_models`` drain loop.

    Tags every packet with ``model_index`` and places it on ``merged_queue``
    as a ``(model_idx, packet)`` tuple for ordered consumption downstream.

    Args:
        merged_queue: Shared queue owned by ``_run_models``.
        model_idx: Index embedded in packet placements (``0`` for N=1 runs).
        drain_done: Optional event set by ``_run_models`` when the drain loop
            exits early (e.g. HTTP disconnect). When set, ``emit`` returns
            immediately so worker threads can exit fast.
    """

    def __init__(
        self,
        merged_queue: Queue[tuple[int, Packet | Exception | object]],
        model_idx: int = 0,
        drain_done: threading.Event | None = None,
    ) -> None:
        self._model_idx = model_idx
        self._merged_queue = merged_queue
        self._drain_done = drain_done

    def emit(self, packet: Packet) -> None:
        if self._drain_done is not None and self._drain_done.is_set():
            return
        base = packet.placement or Placement(turn_index=0)
        tagged = Packet(
            placement=base.model_copy(update={"model_index": self._model_idx}),
            obj=packet.obj,
        )
        self._merged_queue.put((self._model_idx, tagged))
