import json

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import DocumentSourceDescription
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.prompts.filter_extration import FILE_SOURCE_WARNING
from onyx.prompts.filter_extration import SOURCE_FILTER_PROMPT
from onyx.prompts.filter_extration import SOURCES_KEY
from onyx.prompts.filter_extration import WEB_SOURCE_WARNING
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()


def strings_to_document_sources(source_strs: list[str]) -> list[DocumentSource]:
    sources = []
    for s in source_strs:
        try:
            sources.append(DocumentSource(s))
        except ValueError:
            logger.warning("Failed to translate %s to a DocumentSource", s)
    return sources


def _history_to_messages(
    history: list[ChatMinimalTextMessage],
) -> list[ChatCompletionMessage]:
    messages: list[ChatCompletionMessage] = []
    for msg in history:
        if msg.message_type == MessageType.USER:
            messages.append(UserMessage(content=msg.message))
        elif msg.message_type == MessageType.ASSISTANT:
            messages.append(AssistantMessage(content=msg.message))
    return messages


def _parse_source_filter_response(
    content: str | None, connected_sources: list[DocumentSource]
) -> list[DocumentSource] | None:
    """Parse the LLM JSON response into validated sources, failing open to None."""
    if not content:
        return None

    # Tolerate code fences / prose around the JSON.
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Source filter extraction returned non-JSON output")
        return None

    raw_sources = data.get(SOURCES_KEY)
    if not isinstance(raw_sources, list) or not raw_sources:
        return None

    allowed = set(connected_sources)
    detected = [
        source
        for source in strings_to_document_sources([str(s) for s in raw_sources])
        if source in allowed
    ]
    return detected or None


def extract_source_filter(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
    connected_sources: list[DocumentSource],
) -> list[DocumentSource] | None:
    """Infer which connectors the user wants to scope the search to.

    Returns the subset of `connected_sources` the user is explicitly limiting
    the search to, or None if they aren't scoping (search everything). Fails
    open to None on any error so it can never break the search.
    """
    if not history or not connected_sources:
        return None

    last_user_idx = next(
        (
            i
            for i in range(len(history) - 1, -1, -1)
            if history[i].message_type == MessageType.USER
        ),
        None,
    )
    if last_user_idx is None:
        return None

    valid_sources = "\n".join(
        f"- {source.value}: {DocumentSourceDescription.get(source, source.value)}"
        for source in connected_sources
    )
    system_msg = SystemMessage(
        content=SOURCE_FILTER_PROMPT.format(
            valid_sources=valid_sources,
            web_source_warning=(
                WEB_SOURCE_WARNING if DocumentSource.WEB in connected_sources else ""
            ),
            file_source_warning=(
                FILE_SOURCE_WARNING if DocumentSource.FILE in connected_sources else ""
            ),
            sample_response=json.dumps({SOURCES_KEY: [connected_sources[0].value]}),
        )
    )

    messages: list[ChatCompletionMessage] = [system_msg]
    messages.extend(_history_to_messages(history[: last_user_idx + 1]))

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
        logger.exception("Source filter extraction failed; searching all sources")
        return None

    return _parse_source_filter_response(content, connected_sources)
