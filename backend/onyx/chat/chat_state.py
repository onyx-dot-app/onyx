import threading
import time
from collections.abc import Callable
from collections.abc import Generator
from queue import Empty
from typing import Any

from onyx.chat.citation_processor import CitationMapping
from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.tools.models import ToolCallInfo
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import wait_on_background


class ChatStateContainer:
    """Container for accumulating state during LLM loop execution.

    This container holds the partial state that can be saved to the database
    if the generation is stopped by the user or completes normally.

    Thread-safe: All write operations are protected by a lock to ensure safe
    concurrent access from multiple threads. For thread-safe reads, use the
    getter methods. Direct attribute access is not thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # These are collected at the end after the entire tool call is completed
        self.tool_calls: list[ToolCallInfo] = []
        # This is accumulated during the streaming
        self.reasoning_tokens: str | None = None
        # This is accumulated during the streaming of the answer
        self.answer_tokens: str | None = None
        # Store citation mapping for building citation_docs_info during partial saves
        self.citation_to_doc: CitationMapping = {}
        # True if this turn is a clarification question (deep research flow)
        self.is_clarification: bool = False
        # Note: LLM cost tracking is now handled in multi_llm.py

    def add_tool_call(self, tool_call: ToolCallInfo) -> None:
        """Add a tool call to the accumulated state."""
        with self._lock:
            self.tool_calls.append(tool_call)

    def set_reasoning_tokens(self, reasoning: str | None) -> None:
        """Set the reasoning tokens from the final answer generation."""
        with self._lock:
            self.reasoning_tokens = reasoning

    def set_answer_tokens(self, answer: str | None) -> None:
        """Set the answer tokens from the final answer generation."""
        with self._lock:
            self.answer_tokens = answer

    def set_citation_mapping(self, citation_to_doc: CitationMapping) -> None:
        """Set the citation mapping from citation processor."""
        with self._lock:
            self.citation_to_doc = citation_to_doc

    def set_is_clarification(self, is_clarification: bool) -> None:
        """Set whether this turn is a clarification question."""
        with self._lock:
            self.is_clarification = is_clarification

    def get_answer_tokens(self) -> str | None:
        """Thread-safe getter for answer_tokens."""
        with self._lock:
            return self.answer_tokens

    def get_reasoning_tokens(self) -> str | None:
        """Thread-safe getter for reasoning_tokens."""
        with self._lock:
            return self.reasoning_tokens

    def get_tool_calls(self) -> list[ToolCallInfo]:
        """Thread-safe getter for tool_calls (returns a copy)."""
        with self._lock:
            return self.tool_calls.copy()

    def get_citation_to_doc(self) -> CitationMapping:
        """Thread-safe getter for citation_to_doc (returns a copy)."""
        with self._lock:
            return self.citation_to_doc.copy()

    def get_is_clarification(self) -> bool:
        """Thread-safe getter for is_clarification."""
        with self._lock:
            return self.is_clarification


def run_chat_loop_with_state_containers(
    func: Callable[..., None],
    completion_callback: Callable[[ChatStateContainer], None],
    is_connected: Callable[[], bool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    *args: Any,
    **kwargs: Any,
) -> Generator[Packet, None]:
    """
    Explicit wrapper function that runs a function in a background thread
    with event streaming capabilities.

    The wrapped function should accept emitter as first arg and use it to emit
    Packet objects. This wrapper polls every 300ms to check if stop signal is set.

    Args:
        func: The function to wrap (should accept emitter and state_container as first and second args)
        emitter: Emitter instance for sending packets
        state_container: ChatStateContainer instance for accumulating state
        is_connected: Callable that returns False when stop signal is set
        *args: Additional positional arguments for func
        **kwargs: Additional keyword arguments for func

    Usage:
        packets = run_chat_loop_with_state_containers(
            my_func,
            emitter=emitter,
            state_container=state_container,
            is_connected=check_func,
            arg1, arg2, kwarg1=value1
        )
        for packet in packets:
            # Process packets
            pass
    """

    def run_with_exception_capture() -> None:
        try:
            # Ensure state_container is passed explicitly, removing it from kwargs if present
            kwargs_with_state = {**kwargs, "state_container": state_container}
            func(emitter, *args, **kwargs_with_state)
        except Exception as e:
            # If execution fails, emit an exception packet
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=0),
                    obj=PacketException(type="error", exception=e),
                )
            )

    # Run the function in a background thread
    thread = run_in_background(run_with_exception_capture)

    pkt: Packet | None = None
    last_turn_index = 0  # Track the highest turn_index seen for stop packet
    last_cancel_check = time.monotonic()
    cancel_check_interval = 0.3  # Check for cancellation every 300ms
    try:
        while True:
            # Poll queue with 300ms timeout for natural stop signal checking
            # the 300ms timeout is to avoid busy-waiting and to allow the stop signal to be checked regularly
            try:
                pkt = emitter.bus.get(timeout=0.3)
            except Empty:
                if not is_connected():
                    # Stop signal detected
                    yield Packet(
                        placement=Placement(turn_index=last_turn_index + 1),
                        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
                    )
                    break
                last_cancel_check = time.monotonic()
                continue

            if pkt is not None:
                # Track the highest turn_index for the stop packet
                if pkt.placement and pkt.placement.turn_index > last_turn_index:
                    last_turn_index = pkt.placement.turn_index

                if isinstance(pkt.obj, OverallStop):
                    yield pkt
                    break
                elif isinstance(pkt.obj, PacketException):
                    raise pkt.obj.exception
                else:
                    yield pkt

                # Check for cancellation periodically even when packets are flowing
                # This ensures stop signal is checked during active streaming
                current_time = time.monotonic()
                if current_time - last_cancel_check >= cancel_check_interval:
                    if not is_connected():
                        # Stop signal detected during streaming
                        yield Packet(
                            placement=Placement(turn_index=last_turn_index + 1),
                            obj=OverallStop(type="stop", stop_reason="user_cancelled"),
                        )
                        break
                    last_cancel_check = current_time
    finally:
        # Wait for thread to complete on normal exit to propagate exceptions and ensure cleanup.
        # Skip waiting if user disconnected to exit quickly.
        if is_connected():
            wait_on_background(thread)
        try:
            completion_callback(state_container)
        except Exception as e:
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=last_turn_index + 1),
                    obj=PacketException(type="error", exception=e),
                )
            )
