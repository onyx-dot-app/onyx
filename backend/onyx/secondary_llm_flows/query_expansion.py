from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from onyx.configs.constants import MessageType
from onyx.llm.inference import run_inference
from onyx.llm.interfaces import LLM
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.search_prompts import (
    KEYWORD_REPHRASE_SYSTEM_PROMPT,
    KEYWORD_REPHRASE_USER_PROMPT,
    REPHRASE_CONTEXT_PROMPT,
    SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT,
    SEMANTIC_QUERY_REPHRASE_USER_PROMPT,
)
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()


class KeywordQueries(BaseModel):
    queries: list[str] = Field(max_length=3)


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
) -> list[ModelMessage]:
    """Convert ChatMinimalTextMessage list to ChatCompletionMessage list."""
    messages: list[ModelMessage] = []

    for msg in history:
        if msg.message_type == MessageType.USER:
            user_msg = ModelRequest(parts=[UserPromptPart(msg.message)])
            messages.append(user_msg)
        elif msg.message_type == MessageType.ASSISTANT:
            assistant_msg = ModelResponse(parts=[TextPart(msg.message)])
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
    system_msg = ModelRequest(
        parts=[
            SystemPromptPart(
                SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT.format(
                    current_date=current_datetime_str
                )
            )
        ]
    )

    # Convert chat history to message format (excluding the last user message and everything after it)
    messages: list[ModelMessage] = [system_msg]
    messages.extend(_build_message_history(history[:last_user_message_idx]))

    # Add the last message as the user prompt with instructions
    final_user_msg = ModelRequest(
        parts=[
            UserPromptPart(
                SEMANTIC_QUERY_REPHRASE_USER_PROMPT.format(
                    additional_context=additional_context, user_query=user_query
                )
            )
        ]
    )
    messages.append(final_user_msg)

    final_query = run_inference(
        llm=llm,
        messages=messages,
        output_type=str,
        flow=LLMFlow.SEMANTIC_QUERY_REPHRASE,
    )

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
    system_msg = ModelRequest(
        parts=[
            SystemPromptPart(
                KEYWORD_REPHRASE_SYSTEM_PROMPT.format(current_date=current_datetime_str)
            )
        ]
    )

    # Convert chat history to message format (excluding the last user message and everything after it)
    messages: list[ModelMessage] = [system_msg]
    messages.extend(_build_message_history(history[:last_user_message_idx]))

    # Add the last message as the user prompt with instructions
    final_user_msg = ModelRequest(
        parts=[
            UserPromptPart(
                KEYWORD_REPHRASE_USER_PROMPT.format(
                    additional_context=additional_context, user_query=user_query
                )
            )
        ]
    )
    messages.append(final_user_msg)

    result = run_inference(
        llm=llm,
        messages=messages,
        output_type=KeywordQueries,
        flow=LLMFlow.KEYWORD_QUERY_EXPANSION,
    )
    return [query.strip() for query in result.queries if query.strip()]
