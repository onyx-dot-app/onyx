from __future__ import annotations

import abc
import contextvars
from types import TracebackType
from typing import Any
from typing import TYPE_CHECKING

from . import util
from .scope import Scope

if TYPE_CHECKING:
    from .processor_interface import TracingProcessor


class Trace(abc.ABC):
    """A complete end-to-end workflow containing related spans and metadata.

    A trace represents a logical workflow or operation (e.g., "Customer Service Query"
    or "Code Generation") and contains all the spans (individual operations) that occur
    during that workflow.

    Example:
        ```python
        # Basic trace usage
        with trace("Order Processing") as t:
            validation_result = await Runner.run(validator, order_data)
            if validation_result.approved:
                await Runner.run(processor, order_data)

        # Trace with metadata and grouping
        with trace(
            "Customer Service",
            group_id="chat_123",
            metadata={"customer": "user_456"}
        ) as t:
            result = await Runner.run(support_agent, query)
        ```

    Notes:
        - Use descriptive workflow names
        - Group related traces with consistent group_ids
        - Add relevant metadata for filtering/analysis
        - Use context managers for reliable cleanup
        - Consider privacy when adding trace data
    """

    @abc.abstractmethod
    def __enter__(self) -> Trace:
        pass

    @abc.abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    @abc.abstractmethod
    def start(self, mark_as_current: bool = False) -> None:
        """Start the trace and optionally mark it as the current trace.

        Args:
            mark_as_current: If true, marks this trace as the current trace
                in the execution context.

        Notes:
            - Must be called before any spans can be added
            - Only one trace can be current at a time
            - Thread-safe when using mark_as_current
        """

    @abc.abstractmethod
    def finish(self, reset_current: bool = False) -> None:
        """Finish the trace and optionally reset the current trace.

        Args:
            reset_current: If true, resets the current trace to the previous
                trace in the execution context.

        Notes:
            - Must be called to complete the trace
            - Finalizes all open spans
            - Thread-safe when using reset_current
        """

    @property
    @abc.abstractmethod
    def trace_id(self) -> str:
        """Get the unique identifier for this trace.

        Returns:
            str: The trace's unique ID in the format 'trace_<32_alphanumeric>'

        Notes:
            - IDs are globally unique
            - Used to link spans to their parent trace
            - Can be used to look up traces in the dashboard
        """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Get the human-readable name of this workflow trace.

        Returns:
            str: The workflow name (e.g., "Customer Service", "Data Processing")

        Notes:
            - Should be descriptive and meaningful
            - Used for grouping and filtering in the dashboard
            - Helps identify the purpose of the trace
        """

    @abc.abstractmethod
    def export(self) -> dict[str, Any] | None:
        """Export the trace data as a serializable dictionary.

        Returns:
            dict | None: Dictionary containing trace data, or None if tracing is disabled.

        Notes:
            - Includes all spans and their data
            - Used for sending traces to backends
            - May include metadata and group ID
        """


class NoOpTrace(Trace):
    """A no-op implementation of Trace that doesn't record any data.

    Used when tracing is disabled but trace operations still need to work.
    Maintains proper context management but doesn't store or export any data.

    Example:
        ```python
        # When tracing is disabled, traces become NoOpTrace
        with trace("Disabled Workflow") as t:
            # Operations still work but nothing is recorded
            await Runner.run(agent, "query")
        ```
    """

    def __init__(self) -> None:
        self._started = False
        self._prev_context_token: contextvars.Token[Trace | None] | None = None

    def __enter__(self) -> Trace:
        if self._started:
            return self

        self._started = True
        self.start(mark_as_current=True)

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.finish(reset_current=True)

    def start(self, mark_as_current: bool = False) -> None:
        if mark_as_current:
            self._prev_context_token = Scope.set_current_trace(self)

    def finish(self, reset_current: bool = False) -> None:
        if reset_current and self._prev_context_token is not None:
            Scope.reset_current_trace(self._prev_context_token)
            self._prev_context_token = None

    @property
    def trace_id(self) -> str:
        """The trace's unique identifier.

        Returns:
            str: A unique ID for this trace.
        """
        return "no-op"

    @property
    def name(self) -> str:
        """The workflow name for this trace.

        Returns:
            str: Human-readable name describing this workflow.
        """
        return "no-op"

    def export(self) -> dict[str, Any] | None:
        """Export the trace data as a dictionary.

        Returns:
            dict | None: Trace data in exportable format, or None if no data.
        """
        return None


NO_OP_TRACE = NoOpTrace()


class TraceImpl(Trace):
    """
    A trace that will be recorded by the tracing library.
    """

    __slots__ = (
        "_name",
        "_trace_id",
        "group_id",
        "metadata",
        "_prev_context_token",
        "_processor",
        "_started",
    )

    def __init__(
        self,
        name: str,
        trace_id: str | None,
        group_id: str | None,
        metadata: dict[str, Any] | None,
        processor: TracingProcessor,
    ):
        self._name = name
        self._trace_id = trace_id or util.gen_trace_id()
        self.group_id = group_id
        self.metadata = metadata
        self._prev_context_token: contextvars.Token[Trace | None] | None = None
        self._processor = processor
        self._started = False

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def name(self) -> str:
        return self._name

    def start(self, mark_as_current: bool = False) -> None:
        if self._started:
            return

        self._started = True
        self._processor.on_trace_start(self)

        if mark_as_current:
            self._prev_context_token = Scope.set_current_trace(self)

    def finish(self, reset_current: bool = False) -> None:
        if not self._started:
            return

        self._processor.on_trace_end(self)

        if reset_current and self._prev_context_token is not None:
            Scope.reset_current_trace(self._prev_context_token)
            self._prev_context_token = None

    def __enter__(self) -> Trace:
        if self._started:
            return self

        self.start(mark_as_current=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.finish(reset_current=exc_type is not GeneratorExit)

    def export(self) -> dict[str, Any] | None:
        return {
            "object": "trace",
            "id": self.trace_id,
            "workflow_name": self.name,
            "group_id": self.group_id,
            "metadata": self.metadata,
        }
