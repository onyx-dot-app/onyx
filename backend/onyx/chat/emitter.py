import threading
from enum import Enum
from queue import Full, Queue

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ModelStreamStatus(str, Enum):
    DONE = "done"


class Emitter:
    """Tag packets with their model index and send them to the chat coordinator."""

    def __init__(
        self,
        merged_queue: Queue[tuple[int, Packet | ModelStreamStatus]],
        response_id: int,
        model_idx: int = 0,
        drain_done: threading.Event | None = None,
    ) -> None:
        self._model_idx = model_idx
        self.response_id = response_id
        self._merged_queue = merged_queue
        self._drain_done = drain_done

    def emit(self, packet: Packet) -> None:
        if self._drain_done is not None and self._drain_done.is_set():
            return
        base = packet.placement or Placement(turn_index=0)
        tagged = Packet(
            placement=base.model_copy(update={"model_index": self._model_idx}),
            obj=packet.obj,
            identity=packet.identity,
        )
        try:
            self._merged_queue.put_nowait((self._model_idx, tagged))
        except Full:
            logger.error(
                "Chat event delivery exceeded its bound; use persisted history"
            )
            if self._drain_done is not None:
                self._drain_done.set()
