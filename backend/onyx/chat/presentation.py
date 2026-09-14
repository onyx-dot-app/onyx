"""Project Agent events into chat packets and partial display state."""

from onyx.agents.events import (
    AgentEvent,
    MessageEndEvent,
    MessageUpdateEvent,
    ToolResultEvent,
)
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.chat.renderer import PacketRenderer, RenderConfig
from onyx.llm.models import AssistantMessage, GenerationEvent
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet


class TurnPresentation:
    """Application event consumer. It never drives a model or changes Agent state."""

    def __init__(self, emitter: Emitter) -> None:
        self.emitter = emitter
        self.renderer = PacketRenderer(RenderConfig())
        self.state: ChatStateContainer | None = None
        self.message = AssistantMessage()
        self.calls: dict[str, Placement] = {}

    def placement_for(self, call_id: str) -> Placement:
        # Observer failure must not prevent storage of accepted tool results.
        placement = self.calls.get(call_id)
        return (
            placement.model_copy() if placement is not None else Placement(turn_index=0)
        )

    def emit_tool_packet(self, call_id: str, packet: Packet) -> None:
        placement = self.placement_for(call_id)
        if packet.placement.sub_turn_index is not None:
            placement = placement.model_copy(
                update={
                    "sub_turn_index": packet.placement.sub_turn_index,
                }
            )
        self.emitter.emit(packet.model_copy(update={"placement": placement}))

    def configure(
        self, config: RenderConfig, state: ChatStateContainer | None = None
    ) -> None:
        self.renderer = PacketRenderer(config)
        self.state = state
        self.message = AssistantMessage()

    def consume_model(self, event: GenerationEvent) -> None:
        self.message = event.message
        packets = self.renderer.consume(event)
        self.calls.update(self.renderer.calls)
        # Save display state before publishing packets so Stop sees the same prefix.
        if self.state is not None and event.type != "start":
            self.state.update_display(
                answer=self.renderer.answer,
                reasoning=self.renderer.reasoning,
                request_params=event.request_params,
                citations=self.renderer.citations_emitted,
                pre_answer_seconds=self.renderer.config.pre_answer_seconds
                if self.renderer.answer_started
                else None,
            )
        for packet in packets:
            self.emitter.emit(packet)

    def consume(self, event: AgentEvent) -> None:
        if isinstance(event, MessageUpdateEvent):
            self.consume_model(event.generation_event)
        elif isinstance(event, MessageEndEvent):
            for call in event.message.tool_calls:
                if call.id not in self.calls:
                    self.calls[call.id] = self.renderer.call_placement(call)
        elif (
            isinstance(event, ToolResultEvent)
            and event.type == "tool_update"
            and isinstance(event.result.details, Packet)
        ):
            self.emit_tool_packet(event.tool_call.id, event.result.details)
