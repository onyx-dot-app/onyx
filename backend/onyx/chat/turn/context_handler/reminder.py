"""Task prompt context handler for updating task prompts in agent messages."""

from collections.abc import Sequence

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.prompts.prompt_utils import build_task_prompt_reminders_v2
from onyx.utils.logger import setup_logger

logger = setup_logger()


def maybe_append_reminder(
        agent_turn_messages: Sequence[AgentSDKMessage],
        prompt_config: PromptConfig,
        should_cite_documents: bool,
        last_iteration_included_web_search: bool = False,
        model_provider: str | None = None,
        model_name: str | None = None,
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
        model_provider: LLM provider name (e.g., "openai", "anthropic") for provider-specific logic
        model_name: LLM model name (e.g., "mistral-large-latest", "gpt-4") for model-specific logic

    Returns:
        Updated message list with task prompt reminder appended
    """

    reminder_text = build_task_prompt_reminders_v2(
        prompt_config,
        use_language_hint=False,
        should_cite=should_cite_documents,
        last_iteration_included_web_search=last_iteration_included_web_search,
    )
    if not reminder_text:
        return list(agent_turn_messages)

    text_content: InputTextContent = {
        "type": "input_text",
        "text": reminder_text,
    }
    reminder_message: UserMessage = {"role": "user", "content": [text_content]}

    # Mistral API requires 'assistant' immediately after 'tool' - no other roles allowed
    # For Mistral: place reminder BEFORE agent_turn_messages to satisfy strict role ordering
    # This ensures: user (original) → user (reminder) → assistant (tool_calls) → tool → assistant
    # For other providers: place reminder AFTER agent_turn_messages (standard behavior)
    if ((model_provider and "mistral" in model_provider.lower())
            or (model_name and "mistral" in model_name.lower())):
        logger.debug(f"[REMINDER] Mistral detected (model_name={model_name}) - placing reminder BEFORE agent_turn_messages")
        return [reminder_message] + list(agent_turn_messages)

    return list(agent_turn_messages) + [reminder_message]
