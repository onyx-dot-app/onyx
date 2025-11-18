from __future__ import annotations

import abc
import contextvars
from typing import Any
from typing import Generic
from typing import TypeVar

from typing_extensions import TypedDict

from . import util
from .scope import Scope
from .span_data import SpanData
from onyx.tracing.processor_interface import TracingProcessor

TSpanData = TypeVar("TSpanData", bound=SpanData)


class SpanError(TypedDict):
    """Represents an error that occurred during span execution.

    Attributes:
        message: A human-readable error description
        data: Optional dictionary containing additional error context
    """

    message: str
    data: dict[str, Any] | None


class Span(abc.ABC, Generic[TSpanData]):
    """Base class for representing traceable operations with timing and context.

    A span represents a single operation within a trace (e.g., an LLM call, tool execution,
    or agent run). Spans track timing, relationships between operations, and operation-specific
    data.

    Type Args:
        TSpanData: The type of span-specific data this span contains.

    Example:
        ```python
        # Creating a custom span
        with custom_span("database_query", {
            "operation": "SELECT",
            "table": "users"
        }) as span:
            results = await db.query("SELECT * FROM users")
            span.set_output({"count": len(results)})

        # Handling errors in spans
        with custom_span("risky_operation") as span:
            try:
                result = perform_risky_operation()
            except Exception as e:
                span.set_error({
                    "message": str(e),
                    "data": {"operation": "risky_operation"}
                })
                raise
        ```

        Notes:
        - Spans automatically nest under the current trace
        - Use context managers for reliable start/finish
        - Include relevant data but avoid sensitive information
        - Handle errors properly using set_error()
    """

    @property
    @abc.abstractmethod
    def trace_id(self) -> str:
        """The ID of the trace this span belongs to.

        Returns:
            str: Unique identifier of the parent trace.
        """

    @property
    @abc.abstractmethod
    def span_id(self) -> str:
        """Unique identifier for this span.

        Returns:
            str: The span's unique ID within its trace.
        """

    @property
    @abc.abstractmethod
    def span_data(self) -> TSpanData:
        """Operation-specific data for this span.

        Returns:
            TSpanData: Data specific to this type of span (e.g., LLM generation data).
        """

    @abc.abstractmethod
    def start(self, mark_as_current: bool = False):
        """
        Start the span.

        Args:
            mark_as_current: If true, the span will be marked as the current span.
        """

    @abc.abstractmethod
    def finish(self, reset_current: bool = False) -> None:
        """
        Finish the span.

        Args:
            reset_current: If true, the span will be reset as the current span.
        """

    @abc.abstractmethod
    def __enter__(self) -> Span[TSpanData]:
        pass

    @abc.abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    @abc.abstractmethod
    def parent_id(self) -> str | None:
        """ID of the parent span, if any.

        Returns:
            str | None: The parent span's ID, or None if this is a root span.
        """

    @abc.abstractmethod
    def set_error(self, error: SpanError) -> None:
        pass

    @property
    @abc.abstractmethod
    def error(self) -> SpanError | None:
        """Any error that occurred during span execution.

        Returns:
            SpanError | None: Error details if an error occurred, None otherwise.
        """

    @abc.abstractmethod
    def export(self) -> dict[str, Any] | None:
        pass

    @property
    @abc.abstractmethod
    def started_at(self) -> str | None:
        """When the span started execution.

        Returns:
            str | None: ISO format timestamp of span start, None if not started.
        """

    @property
    @abc.abstractmethod
    def ended_at(self) -> str | None:
        """When the span finished execution.

        Returns:
            str | None: ISO format timestamp of span end, None if not finished.
        """


class NoOpSpan(Span[TSpanData]):
    """A no-op implementation of Span that doesn't record any data.

    Used when tracing is disabled but span operations still need to work.

    Args:
        span_data: The operation-specific data for this span.
    """

    __slots__ = ("_span_data", "_prev_span_token")

    def __init__(self, span_data: TSpanData):
        self._span_data = span_data
        self._prev_span_token: contextvars.Token[Span[TSpanData] | None] | None = None

    @property
    def trace_id(self) -> str:
        return "no-op"

    @property
    def span_id(self) -> str:
        return "no-op"

    @property
    def span_data(self) -> TSpanData:
        return self._span_data

    @property
    def parent_id(self) -> str | None:
        return None

    def start(self, mark_as_current: bool = False):
        if mark_as_current:
            self._prev_span_token = Scope.set_current_span(self)

    def finish(self, reset_current: bool = False) -> None:
        if reset_current and self._prev_span_token is not None:
            Scope.reset_current_span(self._prev_span_token)
            self._prev_span_token = None

    def __enter__(self) -> Span[TSpanData]:
        self.start(mark_as_current=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        reset_current = True
        if exc_type is GeneratorExit:
            reset_current = False

        self.finish(reset_current=reset_current)

    def set_error(self, error: SpanError) -> None:
        pass

    @property
    def error(self) -> SpanError | None:
        return None

    def export(self) -> dict[str, Any] | None:
        return None

    @property
    def started_at(self) -> str | None:
        return None

    @property
    def ended_at(self) -> str | None:
        return None


class SpanImpl(Span[TSpanData]):
    __slots__ = (
        "_trace_id",
        "_span_id",
        "_parent_id",
        "_started_at",
        "_ended_at",
        "_error",
        "_prev_span_token",
        "_processor",
        "_span_data",
    )

    def __init__(
        self,
        trace_id: str,
        span_id: str | None,
        parent_id: str | None,
        processor: TracingProcessor,
        span_data: TSpanData,
    ):
        self._trace_id = trace_id
        self._span_id = span_id or util.gen_span_id()
        self._parent_id = parent_id
        self._started_at: str | None = None
        self._ended_at: str | None = None
        self._processor = processor
        self._error: SpanError | None = None
        self._prev_span_token: contextvars.Token[Span[TSpanData] | None] | None = None
        self._span_data = span_data

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def span_id(self) -> str:
        return self._span_id

    @property
    def span_data(self) -> TSpanData:
        return self._span_data

    @property
    def parent_id(self) -> str | None:
        return self._parent_id

    def start(self, mark_as_current: bool = False):
        if self.started_at is not None:
            return

        self._started_at = util.time_iso()
        self._processor.on_span_start(self)
        if mark_as_current:
            self._prev_span_token = Scope.set_current_span(self)

    def finish(self, reset_current: bool = False) -> None:
        if self.ended_at is not None:
            return

        self._ended_at = util.time_iso()
        self._processor.on_span_end(self)
        if reset_current and self._prev_span_token is not None:
            Scope.reset_current_span(self._prev_span_token)
            self._prev_span_token = None

    def __enter__(self) -> Span[TSpanData]:
        self.start(mark_as_current=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        reset_current = True
        if exc_type is GeneratorExit:
            reset_current = False

        self.finish(reset_current=reset_current)

    def set_error(self, error: SpanError) -> None:
        self._error = error

    @property
    def error(self) -> SpanError | None:
        return self._error

    @property
    def started_at(self) -> str | None:
        return self._started_at

    @property
    def ended_at(self) -> str | None:
        return self._ended_at

    def export(self) -> dict[str, Any] | None:
        return {
            "object": "trace.span",
            "id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self._parent_id,
            "started_at": self._started_at,
            "ended_at": self._ended_at,
            "span_data": self.span_data.export(),
            "error": self._error,
        }
