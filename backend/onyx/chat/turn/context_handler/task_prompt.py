"""Task prompt context handler for updating task prompts in agent messages."""

from collections.abc import Sequence

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import TextContent
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.prompts.prompt_utils import build_task_prompt_reminders_v2


def update_task_prompt(
    current_user_message: UserMessage,
    agent_turn_messages: Sequence[AgentSDKMessage],
    prompt_config: PromptConfig,
    should_cite_documents: bool,
) -> list[AgentSDKMessage]:
    user_query = _extract_user_query(current_user_message)
    new_task_prompt_text = build_task_prompt_reminders_v2(
        user_query,
        prompt_config,
        use_language_hint=False,
        should_cite=should_cite_documents,
    )
    last_user_idx = max(
        (i for i, m in enumerate(agent_turn_messages) if m.get("role") == "user"),
        default=-1,
    )

    # Filter out last user message and add new task prompt as user message
    filtered_messages: list[AgentSDKMessage] = [
        m for i, m in enumerate(agent_turn_messages) if i != last_user_idx
    ]

    # Create new user message with task prompt wrapped in TextContent
    text_content: TextContent = {"type": "text", "text": new_task_prompt_text}
    new_user_message: UserMessage = {"role": "user", "content": [text_content]}

    return filtered_messages + [new_user_message]


def _extract_user_query(current_user_message: UserMessage) -> str:
    first_content = current_user_message["content"][0]
    # Handle both "text" and "input_text" types
    return first_content["text"]
