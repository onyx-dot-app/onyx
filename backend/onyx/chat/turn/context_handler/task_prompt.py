"""Task prompt context handler for updating task prompts in agent messages."""

from onyx.chat.models import PromptConfig
from onyx.chat.turn.models import ChatTurnContext
from onyx.prompts.prompt_utils import build_task_prompt_reminders_v2


def update_task_prompt(
    chat_history: list[dict],
    current_user_message: dict,
    agent_turn_messages: list[dict],
    ctx: ChatTurnContext,
    prompt_config: PromptConfig,
    should_cite_documents: bool,
) -> list[dict]:
    """Remove last task prompt from agent_turn_messages and insert a new one.

    Only operates on agent_turn_messages, never modifies chat_history.
    Finds the last user message in agent_turn_messages and replaces it with
    a new task prompt.

    Args:
        chat_history: Messages before the current user message (immutable)
        current_user_message: The user message just inputted
        agent_turn_messages: Messages generated during this agent turn
        ctx: Chat turn context
        prompt_config: Prompt configuration for building task prompts
        should_cite_documents: Whether to include citation requirements

    Returns:
        Updated agent_turn_messages with new task prompt
    """
    # Extract the user query from current_user_message
    user_query = _extract_user_query(current_user_message)

    # Build the new task prompt
    new_task_prompt = build_task_prompt_reminders_v2(
        user_query,
        prompt_config,
        use_language_hint=False,
        should_cite=should_cite_documents,
    )

    # Find and remove the last user message in agent_turn_messages
    updated_messages = []
    last_user_idx = -1

    for i, message in enumerate(agent_turn_messages):
        if message.get("role") == "user":
            last_user_idx = i

    # Build the updated messages list
    for i, message in enumerate(agent_turn_messages):
        if i == last_user_idx:
            # Skip this message (will be replaced)
            continue
        updated_messages.append(message)

    # Add the new task prompt at the end
    updated_messages.append({"role": "user", "content": new_task_prompt})

    return updated_messages


def _extract_user_query(current_user_message: dict) -> str:
    """Extract the user query text from the message.

    Args:
        current_user_message: The user message dictionary

    Returns:
        The user query as a string
    """
    content = current_user_message.get("content", "")

    # Handle different content formats
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Extract text from content array (common format)
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text", "")
        # Fallback: join all string items
        return " ".join(str(item) for item in content if isinstance(item, str))
    else:
        return str(content)
