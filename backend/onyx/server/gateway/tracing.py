"""Traces for LLM gateway calls."""

from uuid import UUID

from onyx.server.features.build.turn_tracing import get_craft_turn_trace_id
from onyx.server.gateway.craft_session import CRAFT_SESSION_ID_CONTEXTVAR
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace


def llm_gateway_trace(flow: LLMFlow, model: str) -> Trace:
    """Keep request lifecycles separate while grouping a Craft turn externally."""
    metadata: dict[str, str] = {"flow": flow.value, "model": model}
    craft_session_id = CRAFT_SESSION_ID_CONTEXTVAR.get()
    if craft_session_id is not None:
        metadata["craft_session_id"] = craft_session_id
    if flow == LLMFlow.CRAFT_LLM_GENERATION and craft_session_id is not None:
        turn_trace_id = get_craft_turn_trace_id(UUID(craft_session_id))
        if turn_trace_id is not None:
            metadata["distributed_trace_id"] = turn_trace_id
            metadata["distributed_parent_span_id"] = turn_trace_id[:16]
    return trace("llm_gateway", metadata=metadata)
