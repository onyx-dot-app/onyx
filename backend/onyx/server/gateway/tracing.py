"""Traces for LLM gateway calls."""

from onyx.server.features.build.request_context import craft_trace_metadata
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace


def llm_gateway_trace(flow: LLMFlow, model: str) -> Trace:
    """Keep request lifecycles separate while grouping a Craft turn externally."""
    metadata: dict[str, str] = {"flow": flow.value, "model": model}
    metadata.update(
        craft_trace_metadata(include_turn=flow == LLMFlow.CRAFT_LLM_GENERATION)
    )
    return trace("llm_gateway", metadata=metadata)
