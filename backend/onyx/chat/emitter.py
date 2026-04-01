import logging
import queue
from queue import Queue

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet

logger = logging.getLogger(__name__)


class Emitter:
    """Routes packets from LLM/tool execution to the ``_run_models`` drain loop.

    Tags every packet with ``model_index`` and places it on ``merged_queue``
    as a ``(model_idx, packet)`` tuple for ordered consumption downstream.

    Args:
        merged_queue: Shared queue owned by ``_run_models``.
        model_idx: Index embedded in packet placements (``0`` for N=1 runs).
    """

    def __init__(
        self,
        merged_queue: Queue[tuple[int, Packet | Exception | object]],
        model_idx: int = 0,
    ) -> None:
        self._model_idx = model_idx
        self._merged_queue = merged_queue

    def emit(self, packet: Packet) -> None:
        base = packet.placement or Placement(turn_index=0)
        tagged = Packet(
            placement=base.model_copy(update={"model_index": self._model_idx}),
            obj=packet.obj,
        )
        try:
            self._merged_queue.put((self._model_idx, tagged), timeout=3.0)
        except queue.Full:
            # Drain loop is gone (e.g. GeneratorExit on disconnect); discard packet.
            logger.warning(
                "Emitter model_idx=%d: queue full after 3s timeout, dropping packet %s",
                self._model_idx,
                type(packet.obj).__name__,
            )
