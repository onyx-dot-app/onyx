from collections.abc import Callable

from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.fleet_query_telemetry import QueryObservation


class Emitter:
    """Tag response packets with their model index before delivery."""

    def __init__(
        self,
        publish: Callable[[Packet], None],
        model_idx: int = 0,
        query_observation: QueryObservation | None = None,
    ) -> None:
        self._model_idx = model_idx
        self._publish = publish
        self._query_observation = query_observation

    def llm_step_started(self) -> None:
        if self._query_observation is not None:
            self._query_observation.llm_step_started(model_idx=self._model_idx)

    def emit(self, packet: Packet) -> None:
        if self._query_observation is not None:
            self._query_observation.packet_queued(packet, model_idx=self._model_idx)
        self._publish(
            packet.model_copy(
                update={
                    "placement": packet.placement.model_copy(
                        update={"model_index": self._model_idx}
                    )
                }
            )
        )
