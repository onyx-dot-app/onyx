from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import UserMessage
from onyx.prompts.basic_memory import FULL_MEMORY_UPDATE_PROMPT
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response

logger = setup_logger()

# Maximum number of user messages to include
MAX_USER_MESSAGES = 3
MAX_CHARS_PER_MESSAGE = 500


def _format_chat_history(chat_history: list[ChatMinimalTextMessage]) -> str:
    user_messages = [
        msg for msg in chat_history if msg.message_type == MessageType.USER
    ]

    if not user_messages:
        return "No chat history available."

    # Take the last N user messages
    recent_user_messages = user_messages[-MAX_USER_MESSAGES:]

    formatted_parts = []
    for i, msg in enumerate(recent_user_messages, start=1):
        if len(msg.message) > MAX_CHARS_PER_MESSAGE:
            truncated_message = msg.message[:MAX_CHARS_PER_MESSAGE] + "[...truncated]"
        else:
            truncated_message = msg.message
        formatted_parts.append(f"\nUser message:\n{truncated_message}\n")

    return "".join(formatted_parts).strip()


def _format_existing_memories(existing_memories: list[str]) -> str:
    """Format existing memories as a numbered list (1-indexed for readability)."""
    if not existing_memories:
        return "No existing memories."

    formatted_lines = []
    for i, memory in enumerate(existing_memories, start=1):
        formatted_lines.append(f"{i}. {memory}")

    return "\n".join(formatted_lines)


def _format_user_basic_information(
    user_name: str | None,
    user_email: str | None,
    user_role: str | None,
) -> str:
    """Format user basic information, only including fields that have values."""
    lines = []
    if user_name:
        lines.append(f"User name: {user_name}")
    if user_email:
        lines.append(f"User email: {user_email}")
    if user_role:
        lines.append(f"User role: {user_role}")

    if not lines:
        return ""

    return "\n\n# User Basic Information\n" + "\n".join(lines)


def process_memory_update(
    new_memory: str,
    existing_memories: list[str],
    chat_history: list[ChatMinimalTextMessage],
    llm: LLM,
    user_name: str | None = None,
    user_email: str | None = None,
    user_role: str | None = None,
) -> tuple[str, int | None]:
    """
    Determine if a memory should be added or updated.

    Uses the LLM to analyze the new memory against existing memories and
    determine whether to add it as new or update an existing memory.

    Args:
        new_memory: The new memory text from the memory tool
        existing_memories: List of existing memory strings
        chat_history: Recent chat history for context
        llm: LLM instance to use for the decision
        user_name: Optional user name for context
        user_email: Optional user email for context
        user_role: Optional user role for context

    Returns:
        Tuple of (memory_text, index_to_replace)
        - memory_text: The final memory text to store
        - index_to_replace: Index in existing_memories to replace, or None if adding new
    """
    # Format inputs for the prompt
    formatted_chat_history = _format_chat_history(chat_history)
    formatted_memories = _format_existing_memories(existing_memories)
    formatted_user_info = _format_user_basic_information(
        user_name, user_email, user_role
    )

    # Build the prompt
    prompt = FULL_MEMORY_UPDATE_PROMPT.format(
        chat_history=formatted_chat_history,
        user_basic_information=formatted_user_info,
        existing_memories=formatted_memories,
        new_memory=new_memory,
    )

    # Call LLM with Braintrust tracing
    try:
        prompt_msg = UserMessage(content=prompt)
        with llm_generation_span(
            llm=llm, flow="memory_update", input_messages=[prompt_msg]
        ) as span_generation:
            response = llm.invoke(
                prompt=prompt_msg, reasoning_effort=ReasoningEffort.OFF
            )
            record_llm_response(span_generation, response)
            content = response.choice.message.content
    except Exception as e:
        logger.warning(f"LLM invocation failed for memory update: {e}")
        return (new_memory, None)

    # Handle empty response
    if not content:
        logger.warning(
            "LLM returned empty response for memory update, defaulting to add"
        )
        return (new_memory, None)

    # Parse JSON response
    parsed_response = parse_llm_json_response(content)

    if not parsed_response:
        logger.warning(
            f"Failed to parse JSON from LLM response: {content[:200]}..., defaulting to add"
        )
        return (new_memory, None)

    # Extract fields from response
    operation = parsed_response.get("operation", "add").lower()
    memory_id = parsed_response.get("memory_id")
    memory_text = parsed_response.get("memory_text", new_memory)

    # Ensure memory_text is valid
    if not memory_text or not isinstance(memory_text, str):
        memory_text = new_memory

    # Handle add operation
    if operation == "add":
        logger.debug("Memory update operation: add")
        return (memory_text, None)

    # Handle update operation
    if operation == "update":
        # Validate memory_id
        if memory_id is None:
            logger.warning("Update operation specified but no memory_id provided")
            return (memory_text, None)

        # Convert memory_id to integer if it's a string
        try:
            memory_id_int = int(memory_id)
        except (ValueError, TypeError):
            logger.warning(f"Invalid memory_id format: {memory_id}")
            return (memory_text, None)

        # Convert from 1-indexed (LLM response) to 0-indexed (internal)
        index_to_replace = memory_id_int - 1

        # Validate index is in range
        if index_to_replace < 0 or index_to_replace >= len(existing_memories):
            logger.warning(
                f"memory_id {memory_id_int} out of range (1-{len(existing_memories)}), defaulting to add"
            )
            return (memory_text, None)

        logger.debug(f"Memory update operation: update at index {index_to_replace}")
        return (memory_text, index_to_replace)

    # Unknown operation, default to add
    logger.warning(f"Unknown operation '{operation}', defaulting to add")
    return (memory_text, None)
