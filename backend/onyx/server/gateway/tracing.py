"""Traces for LLM gateway calls."""

from onyx.server.gateway.craft_session import CRAFT_SESSION_ID_CONTEXTVAR
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace


def llm_gateway_trace(flow: LLMFlow, model: str) -> Trace:
    """One trace per gateway call.

    Tagged with the calling Craft session when one is bound to the request,
    so a session's LLM calls can be found by filtering on ``craft_session_id``.
    """
    metadata: dict[str, str] = {"flow": flow.value, "model": model}
    craft_session_id = CRAFT_SESSION_ID_CONTEXTVAR.get()
    if craft_session_id is not None:
        metadata["craft_session_id"] = craft_session_id
    return trace("llm_gateway", metadata=metadata)
