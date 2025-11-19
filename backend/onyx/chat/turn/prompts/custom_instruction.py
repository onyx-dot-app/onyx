"""Custom instruction context handler for adding custom instructions to agent messages."""

from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig


def build_custom_instructions(
    prompt_config: PromptConfig,
) -> list[UserMessage]:
    """Add custom instructions as a user message if present in prompt_config.

    This function adds a user message containing custom instructions before
    the task prompt reminder. Custom instructions are only added if they
    exist in the prompt_config.

    Args:
        agent_turn_messages: Messages from the current agent turn iteration
        prompt_config: Configuration containing custom_instruction field

    Returns:
        Updated message list with custom instruction user message appended (if applicable)
    """
    if not prompt_config.custom_instructions:
        return []

    custom_instruction_text = (
        f"Custom Instructions: {prompt_config.custom_instructions}"
    )

    text_content: InputTextContent = {
        "type": "input_text",
        "text": custom_instruction_text,
    }
    custom_instruction_message: UserMessage = {
        "role": "user",
        "content": [text_content],
    }

    return [custom_instruction_message]
