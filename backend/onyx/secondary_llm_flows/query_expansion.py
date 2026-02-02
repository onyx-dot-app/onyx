from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.search_prompts import KEYWORD_REPHRASE_SYSTEM_PROMPT
from onyx.prompts.search_prompts import KEYWORD_REPHRASE_USER_PROMPT
from onyx.prompts.search_prompts import REPHRASE_CONTEXT_PROMPT
from onyx.prompts.search_prompts import SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT
from onyx.prompts.search_prompts import SEMANTIC_QUERY_REPHRASE_USER_PROMPT
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_span_output
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_additional_context(
    user_info: str | None = None,
    memories: list[str] | None = None,
) -> str:
    """Build additional context section for query rephrasing/expansion.

    Returns empty string if both user_info and memories are None/empty.
    Otherwise returns formatted context with "N/A" for missing fields.
    """
    has_user_info = user_info and user_info.strip()
    has_memories = memories and any(m.strip() for m in memories)

    if not has_user_info and not has_memories:
        return ""

    formatted_user_info = user_info if has_user_info else "N/A"
    formatted_memories = (
        "\n".join(f"- {memory}" for memory in memories)
        if has_memories and memories
        else "N/A"
    )

    return REPHRASE_CONTEXT_PROMPT.format(
        user_info=formatted_user_info,
        memories=formatted_memories,
    )


def _build_message_history(
    history: list[ChatMinimalTextMessage],
) -> list[ChatCompletionMessage]:
    """Convert ChatMinimalTextMessage list to ChatCompletionMessage list."""
    messages: list[ChatCompletionMessage] = []

    for msg in history:
        if msg.message_type == MessageType.USER:
            user_msg = UserMessage(content=msg.message)
            messages.append(user_msg)
        elif msg.message_type == MessageType.ASSISTANT:
            assistant_msg = AssistantMessage(content=msg.message)
            messages.append(assistant_msg)

    return messages


def semantic_query_rephrase(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
    user_info: str | None = None,
    memories: list[str] | None = None,
) -> str:
    """Rephrase a query into a standalone query using chat history context.

    Converts the user's query into a self-contained search query that incorporates
    relevant context from the chat history and optional user information/memories.

    Args:
        history: Chat message history. Must contain at least one user message.
        llm: Language model to use for rephrasing
        user_info: Optional user information for personalization
        memories: Optional user memories for personalization

    Returns:
        Rephrased standalone query string

    Raises:
        ValueError: If history is empty or contains no user messages
        RuntimeError: If LLM fails to generate a rephrased query
    """
    if not history:
        raise ValueError("History cannot be empty for query rephrasing")

    # Find the last user message in the history
    last_user_message_idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i].message_type == MessageType.USER:
            last_user_message_idx = i
            break

    if last_user_message_idx is None:
        raise ValueError("History must contain at least one user message")

    # Extract the last user query
    user_query = history[last_user_message_idx].message

    # Build additional context section
    additional_context = _build_additional_context(user_info, memories)

    current_datetime_str = get_current_llm_day_time(
        include_day_of_week=True, full_sentence=False
    )

    # Build system message with current date
    system_msg = SystemMessage(
        content=SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT.format(
            current_date=current_datetime_str
        )
    )

    # Convert chat history to message format (excluding the last user message and everything after it)
    messages: list[ChatCompletionMessage] = [system_msg]
    messages.extend(_build_message_history(history[:last_user_message_idx]))

    # Add the last message as the user prompt with instructions
    final_user_msg = UserMessage(
        content=SEMANTIC_QUERY_REPHRASE_USER_PROMPT.format(
            additional_context=additional_context, user_query=user_query
        )
    )
    messages.append(final_user_msg)

    # Call LLM and return result with Braintrust tracing
    with llm_generation_span(
        llm=llm, flow="semantic_query_rephrase", input_messages=messages
    ) as span_generation:
        response = llm.invoke(prompt=messages, reasoning_effort=ReasoningEffort.OFF)
        final_query = response.choice.message.content
        record_llm_span_output(span_generation, final_query, response.usage)

    if not final_query:
        # It's ok if some other queries fail, this one is likely the best one
        # It also can't fail in parsing so we should be able to guarantee a valid query here.
        raise RuntimeError("LLM failed to generate a rephrased query")

    return final_query


def keyword_query_expansion(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
    user_info: str | None = None,
    memories: list[str] | None = None,
) -> list[str] | None:
    """Expand a query into multiple keyword-only queries using chat history context.

    Converts the user's query into a set of keyword-based search queries (max 3)
    that incorporate relevant context from the chat history and optional user
    information/memories. Returns a list of keyword queries.

    Args:
        history: Chat message history. Must contain at least one user message.
        llm: Language model to use for keyword expansion
        user_info: Optional user information for personalization
        memories: Optional user memories for personalization

    Returns:
        List of keyword-only query strings (max 3), or empty list if generation fails

    Raises:
        ValueError: If history is empty or contains no user messages
    """
    if not history:
        raise ValueError("History cannot be empty for keyword query expansion")

    # Find the last user message in the history
    last_user_message_idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i].message_type == MessageType.USER:
            last_user_message_idx = i
            break

    if last_user_message_idx is None:
        raise ValueError("History must contain at least one user message")

    # Extract the last user query
    user_query = history[last_user_message_idx].message

    # Build additional context section
    additional_context = _build_additional_context(user_info, memories)

    current_datetime_str = get_current_llm_day_time(
        include_day_of_week=True, full_sentence=False
    )

    # Build system message with current date
    system_msg = SystemMessage(
        content=KEYWORD_REPHRASE_SYSTEM_PROMPT.format(current_date=current_datetime_str)
    )

    # Convert chat history to message format (excluding the last user message and everything after it)
    messages: list[ChatCompletionMessage] = [system_msg]
    messages.extend(_build_message_history(history[:last_user_message_idx]))

    # Add the last message as the user prompt with instructions
    final_user_msg = UserMessage(
        content=KEYWORD_REPHRASE_USER_PROMPT.format(
            additional_context=additional_context, user_query=user_query
        )
    )
    messages.append(final_user_msg)

    # Call LLM and return result with Braintrust tracing
    with llm_generation_span(
        llm=llm, flow="keyword_query_expansion", input_messages=messages
    ) as span_generation:
        response = llm.invoke(prompt=messages, reasoning_effort=ReasoningEffort.OFF)
        content = response.choice.message.content
        record_llm_span_output(span_generation, content, response.usage)

    # Parse the response - each line is a separate keyword query
    if not content:
        return []

    queries = [line.strip() for line in content.strip().split("\n") if line.strip()]
    return queries
