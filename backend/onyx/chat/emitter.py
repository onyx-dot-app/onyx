from collections.abc import Callable

from onyx.server.query_and_chat.streaming_models import Packet


class Emitter:
    """Tag response packets with their model index before delivery."""

    def __init__(
        self,
        publish: Callable[[Packet], None],
        model_idx: int = 0,
    ) -> None:
        self._model_idx = model_idx
        self._publish = publish

    def emit(self, packet: Packet) -> None:
        self._publish(
            packet.model_copy(
                update={
                    "placement": packet.placement.model_copy(
                        update={"model_index": self._model_idx}
                    )
                }
            )
        )
