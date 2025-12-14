from collections.abc import Callable
from collections.abc import Generator
from queue import Empty
from typing import Any

from onyx.chat.emitter import Emitter
from onyx.context.search.models import SearchDoc
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
    """

    def __init__(self) -> None:
        self.tool_calls: list[ToolCallInfo] = []
        self.reasoning_tokens: str | None = None
        self.answer_tokens: str | None = None
        # Store citation mapping for building citation_docs_info during partial saves
        self.citation_to_doc: dict[int, SearchDoc] = {}

    def add_tool_call(self, tool_call: ToolCallInfo) -> None:
        """Add a tool call to the accumulated state."""
        self.tool_calls.append(tool_call)

    def set_reasoning_tokens(self, reasoning: str | None) -> None:
        """Set the reasoning tokens from the final answer generation."""
        self.reasoning_tokens = reasoning

    def set_answer_tokens(self, answer: str | None) -> None:
        """Set the answer tokens from the final answer generation."""
        self.answer_tokens = answer

    def set_citation_mapping(self, citation_to_doc: dict[int, Any]) -> None:
        """Set the citation mapping from citation processor."""
        self.citation_to_doc = citation_to_doc


def run_chat_llm_with_state_containers(
    func: Callable[..., None],
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
        packets = run_chat_llm_with_state_containers(
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
                    turn_index=0,
                    obj=PacketException(type="error", exception=e),
                )
            )

    # Run the function in a background thread
    thread = run_in_background(run_with_exception_capture)

    pkt: Packet | None = None
    try:
        while True:
            # Poll queue with 300ms timeout for natural stop signal checking
            # the 300ms timeout is to avoid busy-waiting and to allow the stop signal to be checked regularly
            try:
                pkt = emitter.bus.get(timeout=0.3)
            except Empty:
                if not is_connected():
                    # Stop signal detected, kill the thread
                    break
                continue

            if pkt is not None:
                if pkt.obj == OverallStop(type="stop"):
                    yield pkt
                    break
                elif isinstance(pkt.obj, PacketException):
                    raise pkt.obj.exception
                else:
                    yield pkt
    finally:
        # Wait for thread to complete on normal exit to propagate exceptions and ensure cleanup.
        # Skip waiting if user disconnected to exit quickly.
        if is_connected():
            wait_on_background(thread)
