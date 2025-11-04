"""Task prompt context handler for updating task prompts in agent messages."""

from collections.abc import Sequence

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.prompts.prompt_utils import build_task_prompt_reminders_v2


def add_reminder(
    current_user_message: UserMessage,
    agent_turn_messages: Sequence[AgentSDKMessage],
    prompt_config: PromptConfig,
    should_cite_documents: bool,
) -> list[AgentSDKMessage]:
    """Add task prompt reminder as a user message.

    This function simply appends the task prompt reminder to the agent turn messages.
    The removal of previous user messages (including previous reminders) is handled
    by the remove_middle_user_messages context handler.

    Args:
        current_user_message: The current user message being processed
        agent_turn_messages: Messages from the current agent turn iteration
        prompt_config: Configuration containing reminder field
        should_cite_documents: Whether citation requirements should be included

    Returns:
        Updated message list with task prompt reminder appended
    """
    user_query = _extract_user_query(current_user_message)
    new_task_prompt_text = build_task_prompt_reminders_v2(
        user_query,
        prompt_config,
        use_language_hint=False,
        should_cite=should_cite_documents,
    )

    text_content: InputTextContent = {
        "type": "input_text",
        "text": new_task_prompt_text,
    }
    new_user_message: UserMessage = {"role": "user", "content": [text_content]}

    return list(agent_turn_messages) + [new_user_message]


def _extract_user_query(current_user_message: UserMessage) -> str:
    pass

    first_content = current_user_message["content"][0]
    # User messages contain InputTextContent or ImageContent
    # Only InputTextContent has "text" field, ImageContent has "image_url"
    if first_content["type"] == "input_text":
        # Type narrow - we know it's InputTextContent based on the type check
        text_content: InputTextContent = first_content  # type: ignore[assignment]
        return text_content["text"]
    # If it's an image content, return empty string or handle appropriately
    return ""
