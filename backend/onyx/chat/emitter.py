import logging
import queue
from queue import Queue

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet

logger = logging.getLogger(__name__)


class Emitter:
    """Routes packets produced during tool and LLM execution to the drain loop.

    Every packet is tagged with ``model_index`` and placed as a
    ``(key, packet)`` tuple on ``merged_queue`` for ``_run_models`` to consume
    and yield downstream.

    Args:
        merged_queue: Shared queue owned by the ``_run_models`` drain loop.
        model_idx: Index embedded in packet placements. Defaults to ``0`` for
            N=1 runs. Each model in a multi-model run receives its own index
            (0, 1, 2…).

    Example::

        mq: queue.Queue = queue.Queue()
        emitter = Emitter(merged_queue=mq, model_idx=0)
        emitter.emit(packet)  # places (0, tagged_packet) on mq
        key, tagged = mq.get_nowait()
    """

    def __init__(
        self,
        merged_queue: "Queue",
        model_idx: int = 0,
    ) -> None:
        self._model_idx = model_idx
        self._merged_queue = merged_queue

    def emit(self, packet: Packet) -> None:
        """Emit a packet, stamping it with ``model_index`` and forwarding to the drain loop.

        Args:
            packet: The packet to emit.
        """
        tagged_placement = Placement(
            turn_index=packet.placement.turn_index if packet.placement else 0,
            tab_index=packet.placement.tab_index if packet.placement else 0,
            sub_turn_index=(
                packet.placement.sub_turn_index if packet.placement else None
            ),
            model_index=self._model_idx,
        )
        tagged_packet = Packet(placement=tagged_placement, obj=packet.obj)
        key = self._model_idx
        try:
            self._merged_queue.put((key, tagged_packet), timeout=3.0)
        except queue.Full:
            # Drain loop is gone (e.g. GeneratorExit on disconnect); discard packet.
            logger.warning(
                "Emitter model_idx=%d: queue full after 3s timeout, dropping packet %s",
                self._model_idx,
                type(packet.obj).__name__,
            )
