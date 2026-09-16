from collections.abc import Callable

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet


class Emitter:
    """Tag response packets with their model index before delivery."""

    def __init__(
        self,
        publish: Callable[[Packet], None],
        response_id: int,
        model_idx: int = 0,
    ) -> None:
        self._model_idx = model_idx
        self.response_id = response_id
        self._publish = publish

    def emit(self, packet: Packet) -> None:
        base = packet.placement or Placement(turn_index=0)
        self._publish(
            Packet(
                placement=base.model_copy(update={"model_index": self._model_idx}),
                obj=packet.obj,
                identity=packet.identity,
            )
        )
