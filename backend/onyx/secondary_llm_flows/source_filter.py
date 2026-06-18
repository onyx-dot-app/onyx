from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.prompts.filter_extration import NEXT_KEY
from onyx.prompts.filter_extration import SOURCE_SCOPE_DECISION_PROMPT
from onyx.prompts.filter_extration import SOURCES_KEY
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response

logger = setup_logger()


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
) -> tuple[list[DocumentSource] | None, DocumentSource | None]:
    """Parse the LLM JSON into (scope_now, next_source), restricted to connected
    sources. Returns (None, None) on anything unparseable or an empty scope."""
    data = parse_llm_json_response(content) if content else None
    if not isinstance(data, dict):
        return None, None

    allowed = set(connected_sources)
    raw = data.get(SOURCES_KEY)
    parsed = (
        strings_to_document_sources([str(s) for s in raw])
        if isinstance(raw, list)
        else []
    )
    # Filter to connected sources, dedupe, preserve order.
    sources = list(dict.fromkeys(s for s in parsed if s in allowed))
    if not sources:
        return None, None

    next_raw = data.get(NEXT_KEY)
    next_candidates = strings_to_document_sources([str(next_raw)]) if next_raw else []
    next_source = next(
        (s for s in next_candidates if s in allowed and s not in sources), None
    )
    return sources, next_source


def decide_search_scope(
    history: list[ChatMinimalTextMessage],
    tried_sources: set[DocumentSource],
    llm: LLM,
    connected_sources: list[DocumentSource],
) -> tuple[list[DocumentSource] | None, DocumentSource | None]:
    """Decide, in one LLM call, which connected source(s) THIS search should cover.

    Given the user-side turns and the sources already tried, returns
    (scope_now, next_source). Fails open to (None, None) — search everything — on
    any error. Stateless: the walk lives in `tried_sources`, supplied by the
    caller, so concurrent searches never share scope state.
    """
    if not connected_sources:
        return None, None

    # Use only user-side turns: they carry the routing intent, and it keeps the
    # request ending on a user message (providers reject assistant-terminated input).
    user_content = "\n\n".join(
        msg.message.strip()
        for msg in history
        if msg.message_type == MessageType.USER and msg.message.strip()
    )
    if not user_content:
        return None, None

    valid_sources = "\n".join(f"- {source.value}" for source in connected_sources)
    tried_str = (
        ", ".join(source.value for source in tried_sources) if tried_sources else "none"
    )
    system_msg = SystemMessage(
        content=SOURCE_SCOPE_DECISION_PROMPT.format(
            valid_sources=valid_sources, tried_sources=tried_str
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
        return None, None

    return _parse_scope_decision(content, connected_sources)
