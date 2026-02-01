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


def score_trace(trace_id: str, score: float, comment: str | None = None) -> None:
    """
    Score a trace across all registered processors that support scoring.

    Args:
        trace_id: The trace ID to score
        score: The score value (typically 0.0 to 1.0, but can be any float)
        comment: Optional comment explaining the score

    Notes:
        - This is typically called from user feedback handlers
        - Processors that don't support scoring will ignore this call
    """
    get_trace_provider().score_trace(trace_id, score, comment)


set_trace_provider(DefaultTraceProvider())
