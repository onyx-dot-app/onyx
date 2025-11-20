from __future__ import annotations

import threading
import uuid
from abc import ABC
from abc import abstractmethod
from datetime import datetime
from datetime import timezone
from typing import Any

from .processor_interface import TracingProcessor
from .scope import Scope
from .spans import NoOpSpan
from .spans import Span
from .spans import SpanImpl
from .spans import TSpanData
from .traces import NoOpTrace
from .traces import Trace
from .traces import TraceImpl
from onyx.utils.logger import setup_logger

logger = setup_logger(__name__)


class SynchronousMultiTracingProcessor(TracingProcessor):
    """
    Forwards all calls to a list of TracingProcessors, in order of registration.
    """

    def __init__(self) -> None:
        # Using a tuple to avoid race conditions when iterating over processors
        self._processors: tuple[TracingProcessor, ...] = ()
        self._lock = threading.Lock()

    def add_tracing_processor(self, tracing_processor: TracingProcessor) -> None:
        """
        Add a processor to the list of processors. Each processor will receive all traces/spans.
        """
        with self._lock:
            self._processors += (tracing_processor,)

    def set_processors(self, processors: list[TracingProcessor]) -> None:
        """
        Set the list of processors. This will replace the current list of processors.
        """
        with self._lock:
            self._processors = tuple(processors)

    def on_trace_start(self, trace: Trace) -> None:
        """
        Called when a trace is started.
        """
        for processor in self._processors:
            try:
                processor.on_trace_start(trace)
            except Exception as e:
                logger.error(
                    f"Error in trace processor {processor} during on_trace_start: {e}"
                )

    def on_trace_end(self, trace: Trace) -> None:
        """
        Called when a trace is finished.
        """
        for processor in self._processors:
            try:
                processor.on_trace_end(trace)
            except Exception as e:
                logger.error(
                    f"Error in trace processor {processor} during on_trace_end: {e}"
                )

    def on_span_start(self, span: Span[Any]) -> None:
        """
        Called when a span is started.
        """
        for processor in self._processors:
            try:
                processor.on_span_start(span)
            except Exception as e:
                logger.error(
                    f"Error in trace processor {processor} during on_span_start: {e}"
                )

    def on_span_end(self, span: Span[Any]) -> None:
        """
        Called when a span is finished.
        """
        for processor in self._processors:
            try:
                processor.on_span_end(span)
            except Exception as e:
                logger.error(
                    f"Error in trace processor {processor} during on_span_end: {e}"
                )

    def shutdown(self) -> None:
        """
        Called when the application stops.
        """
        for processor in self._processors:
            logger.debug(f"Shutting down trace processor {processor}")
            try:
                processor.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down trace processor {processor}: {e}")

    def force_flush(self) -> None:
        """
        Force the processors to flush their buffers.
        """
        for processor in self._processors:
            try:
                processor.force_flush()
            except Exception as e:
                logger.error(f"Error flushing trace processor {processor}: {e}")


class TraceProvider(ABC):
    """Interface for creating traces and spans."""

    @abstractmethod
    def register_processor(self, processor: TracingProcessor) -> None:
        """Add a processor that will receive all traces and spans."""

    @abstractmethod
    def set_processors(self, processors: list[TracingProcessor]) -> None:
        """Replace the list of processors with ``processors``."""

    @abstractmethod
    def get_current_trace(self) -> Trace | None:
        """Return the currently active trace, if any."""

    @abstractmethod
    def get_current_span(self) -> Span[Any] | None:
        """Return the currently active span, if any."""

    @abstractmethod
    def time_iso(self) -> str:
        """Return the current time in ISO 8601 format."""

    @abstractmethod
    def gen_trace_id(self) -> str:
        """Generate a new trace identifier."""

    @abstractmethod
    def gen_span_id(self) -> str:
        """Generate a new span identifier."""

    @abstractmethod
    def gen_group_id(self) -> str:
        """Generate a new group identifier."""

    @abstractmethod
    def create_trace(
        self,
        name: str,
        trace_id: str | None = None,
        group_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        disabled: bool = False,
    ) -> Trace:
        """Create a new trace."""

    @abstractmethod
    def create_span(
        self,
        span_data: TSpanData,
        span_id: str | None = None,
        parent: Trace | Span[Any] | None = None,
        disabled: bool = False,
    ) -> Span[TSpanData]:
        """Create a new span."""

    @abstractmethod
    def shutdown(self) -> None:
        """Clean up any resources used by the provider."""


class DefaultTraceProvider(TraceProvider):
    def __init__(self) -> None:
        self._multi_processor = SynchronousMultiTracingProcessor()

    def register_processor(self, processor: TracingProcessor) -> None:
        """
        Add a processor to the list of processors. Each processor will receive all traces/spans.
        """
        self._multi_processor.add_tracing_processor(processor)

    def set_processors(self, processors: list[TracingProcessor]) -> None:
        """
        Set the list of processors. This will replace the current list of processors.
        """
        self._multi_processor.set_processors(processors)

    def get_current_trace(self) -> Trace | None:
        """
        Returns the currently active trace, if any.
        """
        return Scope.get_current_trace()

    def get_current_span(self) -> Span[Any] | None:
        """
        Returns the currently active span, if any.
        """
        return Scope.get_current_span()

    def time_iso(self) -> str:
        """Return the current time in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()

    def gen_trace_id(self) -> str:
        """Generate a new trace ID."""
        return f"trace_{uuid.uuid4().hex}"

    def gen_span_id(self) -> str:
        """Generate a new span ID."""
        return f"span_{uuid.uuid4().hex[:24]}"

    def gen_group_id(self) -> str:
        """Generate a new group ID."""
        return f"group_{uuid.uuid4().hex[:24]}"

    def create_trace(
        self,
        name: str,
        trace_id: str | None = None,
        group_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        disabled: bool = False,
    ) -> Trace:
        """
        Create a new trace.
        """
        if disabled:
            logger.debug(f"Tracing is disabled. Not creating trace {name}")
            return NoOpTrace()

        trace_id = trace_id or self.gen_trace_id()

        logger.debug(f"Creating trace {name} with id {trace_id}")

        return TraceImpl(
            name=name,
            trace_id=trace_id,
            group_id=group_id,
            metadata=metadata,
            processor=self._multi_processor,
        )

    def create_span(
        self,
        span_data: TSpanData,
        span_id: str | None = None,
        parent: Trace | Span[Any] | None = None,
        disabled: bool = False,
    ) -> Span[TSpanData]:
        """
        Create a new span.
        """
        if disabled:
            logger.debug(f"Tracing is disabled. Not creating span {span_data}")
            return NoOpSpan(span_data)

        trace_id: str
        parent_id: str | None

        if not parent:
            current_span = Scope.get_current_span()
            current_trace = Scope.get_current_trace()
            if current_trace is None:
                logger.error(
                    "No active trace. Make sure to start a trace with `trace()` first "
                    "Returning NoOpSpan."
                )
                return NoOpSpan(span_data)
            elif isinstance(current_trace, NoOpTrace) or isinstance(
                current_span, NoOpSpan
            ):
                logger.debug(
                    f"Parent {current_span} or {current_trace} is no-op, returning NoOpSpan"
                )
                return NoOpSpan(span_data)

            parent_id = current_span.span_id if current_span else None
            trace_id = current_trace.trace_id

        elif isinstance(parent, Trace):
            if isinstance(parent, NoOpTrace):
                logger.debug(f"Parent {parent} is no-op, returning NoOpSpan")
                return NoOpSpan(span_data)
            trace_id = parent.trace_id
            parent_id = None
        elif isinstance(parent, Span):
            if isinstance(parent, NoOpSpan):
                logger.debug(f"Parent {parent} is no-op, returning NoOpSpan")
                return NoOpSpan(span_data)
            parent_id = parent.span_id
            trace_id = parent.trace_id
        else:
            # This should never happen, but mypy needs it
            raise ValueError(f"Invalid parent type: {type(parent)}")

        logger.debug(f"Creating span {span_data} with id {span_id}")

        return SpanImpl(
            trace_id=trace_id,
            span_id=span_id or self.gen_span_id(),
            parent_id=parent_id,
            processor=self._multi_processor,
            span_data=span_data,
        )

    def shutdown(self) -> None:
        try:
            logger.debug("Shutting down trace provider")
            self._multi_processor.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down trace provider: {e}")
