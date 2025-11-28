from .processor_interface import TracingProcessor
from .provider import DefaultTraceProvider
from .setup import get_trace_provider
from .setup import set_trace_provider


def add_trace_processor(span_processor: TracingProcessor) -> None:
    """
    Adds a new trace processor. This processor will receive all traces/spans.
    """
    get_trace_provider().register_processor(span_processor)


def set_trace_processors(processors: list[TracingProcessor]) -> None:
    """
    Set the list of trace processors. This will replace the current list of processors.
    """
    get_trace_provider().set_processors(processors)


set_trace_provider(DefaultTraceProvider())
