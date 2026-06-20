from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.prompts.filter_extration import SOURCE_SCOPE_DECISION_PROMPT
from onyx.prompts.filter_extration import SOURCES_KEY
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response

logger = setup_logger()

# Only the most recent user turns feed the scope decision — older turns add
# tokens and stale directives without helping the current request.
MAX_SOURCE_FILTER_USER_TURNS = 5


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
    """Parse the LLM JSON into the scope to apply, restricted to connected
    sources. Returns None on anything unparseable or an empty scope."""
    data = parse_llm_json_response(content) if content else None
    if not isinstance(data, dict):
        return None

    allowed = set(connected_sources)
    raw = data.get(SOURCES_KEY)
    parsed = (
        strings_to_document_sources([str(s) for s in raw])
        if isinstance(raw, list)
        else []
    )
    # Filter to connected sources, dedupe, preserve order.
    sources = list(dict.fromkeys(s for s in parsed if s in allowed))
    return sources or None


def decide_search_scope(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
    connected_sources: list[DocumentSource],
    already_searched: list[DocumentSource],
) -> list[DocumentSource] | None:
    """Decide, in one LLM call, which connected source(s) an internal search
    should cover, from the routing instructions and the user's request.

    Returns the explicitly-named source(s) to scope to, or None to search
    everything. Fails open to None on any error.

    The flow is stateless: the caller passes `already_searched` (sources covered
    earlier this turn) so a sequential directive advances to the next source.
    """
    if not connected_sources:
        return None

    # Use only user-side turns: they carry the routing intent, and it keeps the
    # request ending on a user message (providers reject assistant-terminated input).
    user_turns = [
        msg.message.strip()
        for msg in history
        if msg.message_type == MessageType.USER and msg.message.strip()
    ]
    if not user_turns:
        return None
    # Keep only the most recent turns (the current request plus a little context).
    user_turns = user_turns[-MAX_SOURCE_FILTER_USER_TURNS:]

    # Separate the current request from earlier turns so the model can judge
    # directive lifecycle (persist on a same-topic follow-up, drop a stale
    # directive on an unrelated ask, honor the latest directive).
    current_request = user_turns[-1]
    prior_turns = user_turns[:-1]
    if prior_turns:
        user_content = (
            "[Earlier turns in this conversation]\n"
            + "\n".join(prior_turns)
            + "\n\n[Current request — decide the scope for THIS]\n"
            + current_request
        )
    else:
        user_content = current_request

    valid_sources = "\n".join(f"- {source.value}" for source in connected_sources)
    searched_str = (
        ", ".join(source.value for source in already_searched) or "(none yet)"
    )
    system_msg = SystemMessage(
        content=SOURCE_SCOPE_DECISION_PROMPT.format(
            valid_sources=valid_sources, already_searched=searched_str
        )
    )
    messages: list[ChatCompletionMessage] = [
        system_msg,
        UserMessage(content=user_content),
    ]

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
