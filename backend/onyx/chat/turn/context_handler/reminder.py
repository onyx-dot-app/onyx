"""Task prompt context handler for updating task prompts in agent messages."""

from collections.abc import Sequence

from onyx.chat.models import PromptConfig
from onyx.llm.message_types import ChatCompletionMessage
from onyx.prompts.prompt_utils import build_task_prompt_reminders_v2


def maybe_append_reminder(
    agent_turn_messages: Sequence[ChatCompletionMessage],
    prompt_config: PromptConfig,
    should_cite_documents: bool,
    last_iteration_included_web_search: bool = False,
) -> list[ChatCompletionMessage]:
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
    reminder_text = build_task_prompt_reminders_v2(
        prompt_config,
        use_language_hint=False,
        should_cite=should_cite_documents,
        last_iteration_included_web_search=last_iteration_included_web_search,
    )
    if not reminder_text:
        return list(agent_turn_messages)

    reminder_message: ChatCompletionMessage = {
        "role": "user",
        "content": reminder_text,
    }

    return list(agent_turn_messages) + [reminder_message]
