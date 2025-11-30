from collections.abc import Callable

from onyx.configs.constants import MessageType
from onyx.llm.exceptions import GenAIDisabledException
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import UserMessage
from onyx.llm.utils import dict_based_prompt_to_langchain_prompt
from onyx.llm.utils import message_to_string
from onyx.prompts.miscellaneous_prompts import LANGUAGE_REPHRASE_PROMPT
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.search_prompts import KEYWORD_REPHRASE_SYSTEM_PROMPT
from onyx.prompts.search_prompts import KEYWORD_REPHRASE_USER_PROMPT
from onyx.prompts.search_prompts import REPHRASE_CONTEXT_PROMPT
from onyx.prompts.search_prompts import SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT
from onyx.prompts.search_prompts import SEMANTIC_QUERY_REPHRASE_USER_PROMPT
from onyx.tools.models import ChatMinimalTextMessage
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import count_punctuation
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

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
            user_msg: UserMessage = {
                "role": "user",
                "content": msg.message,
            }
            messages.append(user_msg)
        elif msg.message_type == MessageType.ASSISTANT:
            assistant_msg: AssistantMessage = {
                "role": "assistant",
                "content": msg.message,
            }
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
    system_msg: SystemMessage = {
        "role": "system",
        "content": SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT.format(
            current_date=current_datetime_str
        ),
    }

    # Convert chat history to message format (excluding the last user message and everything after it)
    messages: list[ChatCompletionMessage] = [system_msg]
    messages.extend(_build_message_history(history[:last_user_message_idx]))

    # Add the last message as the user prompt with instructions
    final_user_msg: UserMessage = {
        "role": "user",
        "content": SEMANTIC_QUERY_REPHRASE_USER_PROMPT.format(
            additional_context=additional_context,
            user_query=user_query,
        ),
    }
    messages.append(final_user_msg)

    # Call LLM and return result
    response = llm.invoke(prompt=messages)

    final_query = response.choice.message.content

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
    system_msg: SystemMessage = {
        "role": "system",
        "content": KEYWORD_REPHRASE_SYSTEM_PROMPT.format(
            current_date=current_datetime_str
        ),
    }

    # Convert chat history to message format (excluding the last user message and everything after it)
    messages: list[ChatCompletionMessage] = [system_msg]
    messages.extend(_build_message_history(history[:last_user_message_idx]))

    # Add the last message as the user prompt with instructions
    final_user_msg: UserMessage = {
        "role": "user",
        "content": KEYWORD_REPHRASE_USER_PROMPT.format(
            additional_context=additional_context,
            user_query=user_query,
        ),
    }
    messages.append(final_user_msg)

    # Call LLM and return result
    response = llm.invoke(prompt=messages)
    content = response.choice.message.content

    # Parse the response - each line is a separate keyword query
    if not content:
        return []

    queries = [line.strip() for line in content.strip().split("\n") if line.strip()]
    return queries


def llm_multilingual_query_expansion(query: str, language: str) -> str:
    def _get_rephrase_messages() -> list[dict[str, str]]:
        messages = [
            {
                "role": "user",
                "content": LANGUAGE_REPHRASE_PROMPT.format(
                    query=query, target_language=language
                ),
            },
        ]

        return messages

    try:
        _, fast_llm = get_default_llms(timeout=5)
    except GenAIDisabledException:
        logger.warning(
            "Unable to perform multilingual query expansion, Gen AI disabled"
        )
        return query

    messages = _get_rephrase_messages()
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    model_output = message_to_string(fast_llm.invoke_langchain(filled_llm_prompt))
    logger.debug(model_output)

    return model_output


def multilingual_query_expansion(
    query: str,
    expansion_languages: list[str],
    use_threads: bool = True,
) -> list[str]:
    languages = [language.strip() for language in expansion_languages]
    if use_threads:
        functions_with_args: list[tuple[Callable, tuple]] = [
            (llm_multilingual_query_expansion, (query, language))
            for language in languages
        ]

        query_rephrases = run_functions_tuples_in_parallel(functions_with_args)
        return query_rephrases

    else:
        query_rephrases = [
            llm_multilingual_query_expansion(query, language) for language in languages
        ]
        return query_rephrases


# The stuff below is old and should be retired
OLD_HISTORY_QUERY_REPHRASE = """
Given the following conversation and a follow up input, rephrase the follow up into a SHORT, \
standalone query (which captures any relevant context from previous messages) for a vectorstore.
IMPORTANT: EDIT THE QUERY TO BE AS CONCISE AS POSSIBLE. Respond with a short, compressed phrase \
with mainly keywords instead of a complete sentence.
If there is a clear change in topic, disregard the previous messages.
Strip out any information that is not relevant for the retrieval task.
If the follow up message is an error or code snippet, repeat the same input back EXACTLY.

Chat History:
--------------
{chat_history}
--------------

Follow Up Input: {question}
Standalone question (Respond with only the short combined query):
""".strip()


def get_contextual_rephrase_messages(
    question: str,
    history_str: str,
    prompt_template: str = OLD_HISTORY_QUERY_REPHRASE,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "user",
            "content": prompt_template.format(
                question=question, chat_history=history_str
            ),
        },
    ]

    return messages


def thread_based_query_rephrase(
    user_query: str,
    history_str: str,
    llm: LLM | None = None,
    size_heuristic: int = 200,
    punctuation_heuristic: int = 10,
) -> str:
    if not history_str:
        return user_query

    if len(user_query) >= size_heuristic:
        return user_query

    if count_punctuation(user_query) >= punctuation_heuristic:
        return user_query

    if llm is None:
        try:
            llm, _ = get_default_llms()
        except GenAIDisabledException:
            # If Generative AI is turned off, just return the original query
            return user_query

    prompt_msgs = get_contextual_rephrase_messages(
        question=user_query, history_str=history_str
    )

    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(prompt_msgs)
    rephrased_query = message_to_string(llm.invoke_langchain(filled_llm_prompt))

    logger.debug(f"Rephrased combined query: {rephrased_query}")

    return rephrased_query
