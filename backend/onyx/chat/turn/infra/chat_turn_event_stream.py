import asyncio
import logging
import queue
import threading
from collections.abc import Iterator
from queue import Queue
from typing import Any
from typing import Optional

from agents import Agent
from agents import Runner
from agents import TContext

from onyx.server.query_and_chat.streaming_models import Packet


logger = logging.getLogger(__name__)


class OnyxRunner:
    """
    Spins up an asyncio loop in a background thread, starts Runner.run_streamed there,
    consumes its async event stream, and exposes a blocking .events() iterator.
    """

    def __init__(self) -> None:
        self._q: "queue.Queue[object]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._streamed = None
        self.SENTINEL = object()

    def run_streamed(
        self,
        agent: Agent,
        messages: list[dict],
        context: TContext | None = None,
        max_turns: int = 100,
    ):
        def worker() -> None:
            async def run_and_consume():
                # Create the streamed run *inside* the loop thread
                self._streamed = Runner.run_streamed(
                    agent,
                    messages,
                    context=context,
                    max_turns=max_turns,
                )
                try:
                    async for ev in self._streamed.stream_events():
                        self._q.put(ev)
                finally:
                    self._q.put(self.SENTINEL)

            # Each thread needs its own loop
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(run_and_consume())
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return self

    def events(self) -> Iterator[object]:
        while True:
            ev = self._q.get()
            if ev is self.SENTINEL:
                break
            yield ev

    def cancel(self) -> None:
        # Post a cancellation to the loop thread safely
        if self._loop and self._streamed:

            def _do_cancel() -> None:
                try:
                    self._streamed.cancel()
                except Exception:
                    pass

            self._loop.call_soon_threadsafe(_do_cancel)


def convert_to_packet_obj(packet: dict[str, Any]) -> Any | None:
    """Convert a packet dictionary to PacketObj when possible.

    Args:
        packet: Dictionary containing packet data

    Returns:
        PacketObj instance if conversion is possible, None otherwise
    """
    if not isinstance(packet, dict) or "type" not in packet:
        return None

    packet_type = packet.get("type")
    if not packet_type:
        return None

    try:
        # Import here to avoid circular imports
        from onyx.server.query_and_chat.streaming_models import (
            MessageStart,
            MessageDelta,
            OverallStop,
            SectionEnd,
            SearchToolStart,
            SearchToolDelta,
            ImageGenerationToolStart,
            ImageGenerationToolDelta,
            ImageGenerationToolHeartbeat,
            CustomToolStart,
            CustomToolDelta,
            ReasoningStart,
            ReasoningDelta,
            CitationStart,
            CitationDelta,
        )

        # Map packet types to their corresponding classes
        type_mapping = {
            "response.created": MessageStart,
            "response.output_text.delta": MessageDelta,
            "response.completed": OverallStop,
            "response.output_item.done": SectionEnd,
            "internal_search_tool_start": SearchToolStart,
            "internal_search_tool_delta": SearchToolDelta,
            "image_generation_tool_start": ImageGenerationToolStart,
            "image_generation_tool_delta": ImageGenerationToolDelta,
            "image_generation_tool_heartbeat": ImageGenerationToolHeartbeat,
            "custom_tool_start": CustomToolStart,
            "custom_tool_delta": CustomToolDelta,
            "reasoning_start": ReasoningStart,
            "reasoning_delta": ReasoningDelta,
            "citation_start": CitationStart,
            "citation_delta": CitationDelta,
        }

        packet_class = type_mapping.get(packet_type)
        if packet_class:
            # Create instance using the packet data, filtering out None values
            filtered_data = {k: v for k, v in packet.items() if v is not None}
            if packet_type == "response.output_text.delta":
                filtered_data["type"] = "message_delta"
                filtered_data["content"] = filtered_data["delta"]
            elif packet_type == "response.completed":
                filtered_data["type"] = "stop"
            elif packet_type == "response.created":
                return MessageStart(
                    type="message_start", content="", final_documents=None
                )
            elif packet_type == "response.output_item.done":
                return SectionEnd(type="section_end")
            packet_class(**filtered_data)
            return packet_class(**filtered_data)

    except Exception as e:
        # Log the error but don't fail the entire process
        logger.debug(f"Failed to convert packet to PacketObj: {e}")

    return None


class Emitter:
    """Use this inside tools to emit arbitrary UI progress."""

    def __init__(self, bus: Queue):
        self.bus = bus

    def emit(self, packet: Packet) -> None:
        self.bus.put(packet)
