import json

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import UserMessage
from onyx.prompts.filter_extration import SOURCE_SCOPE_DECISION_PROMPT
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_bracketed_list

logger = setup_logger()

# Only the most recent user turns feed the scope decision — older turns add
# tokens and stale directives without helping the current request.
MAX_SOURCE_FILTER_USER_TURNS = 5


class SearchCycle(BaseModel):
    """One internal_search cycle this turn, as context for the next decision."""

    cycle_number: int
    queries: list[str]
    searched_sources: list[str]


def strings_to_document_sources(source_strs: list[str]) -> list[DocumentSource]:
    sources = []
    for s in source_strs:
        try:
            sources.append(DocumentSource(s))
        except ValueError:
            logger.warning("Failed to translate %s to a DocumentSource", s)
    return sources


def _parse_scope_decision(
    content: str | None, connected_sources: list[DocumentSource]
) -> list[DocumentSource] | None:
    """Parse the model's bracketed list (e.g. `[zendesk, asana]` or `[]`) into the
    scope to apply, restricted to connected sources. Returns None on anything
    unparseable or an empty scope."""
    raw_sources = parse_bracketed_list(content)
    if not raw_sources:
        return None
    allowed = set(connected_sources)
    parsed = strings_to_document_sources(raw_sources)
    # Restrict to connected sources, dedupe, preserve order.
    return list(dict.fromkeys(s for s in parsed if s in allowed)) or None


def decide_search_scope(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
    connected_sources: list[DocumentSource],
    previous_cycles: list[SearchCycle],
    current_queries: list[str],
) -> list[DocumentSource] | None:
    """Decide, in one LLM call, which connected source(s) this internal search
    cycle should cover, from the conversation and the prior cycles this turn.

    Returns the explicitly-named source(s) to scope to, or None to search
    everything. Fails open to None on any error.

    `previous_cycles` is the queries + applied filters of earlier cycles this
    turn; `current_queries` is this cycle's queries. The flow stays stateless and
    the caller supplies both so a backoff sequence can advance to the next source
    when the queries stay on topic, or re-search when they shift.
    """
    # With fewer than two sources there is nothing to scope between.
    if len(connected_sources) < 2:
        return None

    # Only user-side turns carry the routing intent.
    user_turns = [
        msg.message.strip()
        for msg in history
        if msg.message_type == MessageType.USER and msg.message.strip()
    ]
    if not user_turns:
        return None
    user_turns = user_turns[-MAX_SOURCE_FILTER_USER_TURNS:]

    last_user_query = user_turns[-1]
    prior_turns = user_turns[:-1]
    conversation_history = (
        "\n".join(prior_turns)
        if prior_turns
        else "N/A, this is the first message in the conversation."
    )
    previous_cycles_str = (
        json.dumps([cycle.model_dump() for cycle in previous_cycles], indent=2)
        if previous_cycles
        else "N/A This is the first search"
    )
    current_cycle_queries = "\n".join(current_queries) or "N/A"
    valid_sources = "\n".join(source.value for source in connected_sources)

    prompt = SOURCE_SCOPE_DECISION_PROMPT.format(
        conversation_history=conversation_history,
        current_cycle_queries=current_cycle_queries,
        previous_cycles=previous_cycles_str,
        valid_sources=valid_sources,
        last_user_query=last_user_query,
    )
    messages: list[ChatCompletionMessage] = [UserMessage(content=prompt)]

    try:
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.SOURCE_FILTER_EXTRACTION,
            input_messages=messages,
        ) as span_generation:
            response = llm.invoke(prompt=messages, reasoning_effort=ReasoningEffort.OFF)
            record_llm_response(span_generation, response)
            content = response.choice.message.content
    except Exception:
        logger.exception("Source scope decision failed; searching all sources")
        return None

    return _parse_scope_decision(content, connected_sources)
