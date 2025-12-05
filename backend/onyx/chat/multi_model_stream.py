"""
Multi-model streaming infrastructure for concurrent LLM execution.

This module provides classes for running multiple LLM models concurrently
and merging their streaming outputs into a single stream.
"""

import contextvars
import threading
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field
from queue import Empty
from queue import Queue
from typing import Any
from uuid import UUID

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass
class ModelStreamContext:
    """Context for a single model's streaming execution."""

    model_id: str
    emitter: "ModelTaggingEmitter"
    state_container: ChatStateContainer
    thread: threading.Thread | None = None
    completed: bool = False
    error: Exception | None = None
    # Additional data that may be needed for saving chat turns
    extra_data: dict[str, Any] = field(default_factory=dict)


class ModelTaggingEmitter(Emitter):
    """Emitter that tags packets with model_id and forwards to a merged queue.

    This emitter wraps the standard Emitter to add model identification to each
    packet, enabling the frontend to route packets to the correct model's UI.
    """

    def __init__(
        self,
        model_id: str,
        merged_queue: Queue[Packet | None],
        merger: "MultiModelStreamMerger",
    ):
        # Create a local bus for compatibility with existing code that may
        # access emitter.bus directly
        super().__init__(bus=Queue())
        self.model_id = model_id
        self.merged_queue = merged_queue
        self.merger = merger

    def emit(self, packet: Packet) -> None:
        """Emit a packet tagged with this emitter's model_id.

        The packet is forwarded to the merged queue for interleaved streaming.
        """
        # Create a new packet with the model_id set
        tagged_packet = Packet(
            turn_index=packet.turn_index,
            obj=packet.obj,
            model_id=self.model_id,
        )

        # Forward to merged queue for interleaved streaming
        self.merged_queue.put(tagged_packet)

        # Check for completion signals
        if isinstance(packet.obj, OverallStop):
            self.merger.mark_model_complete(self.model_id)


class MultiModelStreamMerger:
    """Merges packet streams from multiple concurrent LLM executions.

    This class manages the concurrent execution of multiple LLM models and
    merges their streaming outputs into a single stream. Each model runs in
    its own thread and emits packets to a shared queue.

    Usage:
        merger = MultiModelStreamMerger(response_group_id=uuid4())

        # Register models and get their emitters
        for model in models:
            ctx = merger.register_model(model_id)
            # Start thread with ctx.emitter

        # Stream merged packets
        for packet in merger.stream(is_connected):
            yield packet
    """

    def __init__(self, response_group_id: UUID):
        self.response_group_id = response_group_id
        self.merged_queue: Queue[Packet | None] = Queue()
        self.model_contexts: dict[str, ModelStreamContext] = {}
        self._lock = threading.Lock()
        self._completed_count = 0
        self._total_models = 0
        self._all_complete = threading.Event()

    def register_model(self, model_id: str) -> ModelStreamContext:
        """Register a model for concurrent streaming.

        Args:
            model_id: Unique identifier for the model (e.g., "openai:gpt-4")

        Returns:
            ModelStreamContext containing the emitter to use for this model.
        """
        with self._lock:
            if model_id in self.model_contexts:
                raise ValueError(f"Model {model_id} already registered")

            emitter = ModelTaggingEmitter(
                model_id=model_id,
                merged_queue=self.merged_queue,
                merger=self,
            )
            state_container = ChatStateContainer()

            context = ModelStreamContext(
                model_id=model_id,
                emitter=emitter,
                state_container=state_container,
            )
            self.model_contexts[model_id] = context
            self._total_models += 1

            return context

    def mark_model_complete(
        self, model_id: str, error: Exception | None = None
    ) -> None:
        """Mark a model's stream as complete.

        Called automatically when an OverallStop packet is emitted,
        or can be called manually on error.

        Args:
            model_id: The model that has completed
            error: Optional exception if the model failed
        """
        with self._lock:
            if model_id in self.model_contexts:
                ctx = self.model_contexts[model_id]
                if not ctx.completed:
                    ctx.completed = True
                    ctx.error = error
                    self._completed_count += 1
                    logger.debug(
                        f"Model {model_id} completed "
                        f"({self._completed_count}/{self._total_models})"
                    )

                    if self._completed_count >= self._total_models:
                        # All models complete - send sentinel to unblock stream
                        self.merged_queue.put(None)
                        self._all_complete.set()

    def start_model_thread(
        self,
        model_id: str,
        target_func: Callable[..., None],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Start a background thread for a model's LLM execution.

        Args:
            model_id: The model to run
            target_func: The function to run (should accept emitter as first arg)
            *args: Additional positional arguments for target_func
            **kwargs: Additional keyword arguments for target_func
        """
        ctx = self.model_contexts.get(model_id)
        if ctx is None:
            raise ValueError(f"Model {model_id} not registered")

        # Copy context vars for the new thread (important for tenant_id, etc.)
        context = contextvars.copy_context()

        def thread_target() -> None:
            try:
                context.run(
                    target_func,
                    ctx.emitter,
                    *args,
                    state_container=ctx.state_container,
                    **kwargs,
                )
            except Exception as e:
                logger.exception(f"Model {model_id} failed: {e}")
                # Emit error packet
                ctx.emitter.emit(
                    Packet(
                        turn_index=0,
                        obj=PacketException(type="error", exception=e),
                    )
                )
                self.mark_model_complete(model_id, error=e)

        thread = threading.Thread(target=thread_target, daemon=True)
        ctx.thread = thread
        thread.start()

    def stream(
        self,
        is_connected: Callable[[], bool],
        poll_timeout: float = 0.3,
    ) -> Iterator[Packet]:
        """Yield merged packets from all models.

        This generator yields packets from all models as they arrive,
        checking the stop signal periodically.

        Args:
            is_connected: Callable that returns False when stop signal is set
            poll_timeout: Timeout for queue polling (seconds)

        Yields:
            Packet objects with model_id set for routing
        """
        while True:
            try:
                packet = self.merged_queue.get(timeout=poll_timeout)

                if packet is None:
                    # All models complete
                    break

                # Check for exception packets - but don't raise, just yield
                # This allows other models to continue streaming
                if isinstance(packet.obj, PacketException):
                    # Log the error but continue streaming other models
                    logger.error(
                        f"Error from model {packet.model_id}: {packet.obj.exception}"
                    )
                    # Still yield the error packet so frontend can show it
                    yield packet
                    continue

                # Check for OverallStop - this indicates one model finished
                # Don't break here, wait for all models
                yield packet

            except Empty:
                # Check stop signal
                if not is_connected():
                    logger.debug("Stop signal detected, stopping all models")
                    break

                # Check if all models completed (defensive)
                if self._all_complete.is_set():
                    break

    def wait_for_threads(self, timeout: float | None = None) -> None:
        """Wait for all model threads to complete.

        Args:
            timeout: Optional timeout per thread (seconds)
        """
        for ctx in self.model_contexts.values():
            if ctx.thread is not None and ctx.thread.is_alive():
                ctx.thread.join(timeout=timeout)

    def get_model_contexts(self) -> dict[str, ModelStreamContext]:
        """Get all model contexts for post-processing (e.g., saving chat turns)."""
        return self.model_contexts.copy()
