"""Task prompt context handler for updating task prompts in agent messages."""

from collections.abc import Sequence

from onyx.chat.models import PromptConfig
from onyx.prompts.prompt_utils import build_task_prompt_reminders_v2


def update_task_prompt(
    current_user_message: dict,  # TODO should this be more strongly typed?
    agent_turn_messages: Sequence[dict],
    prompt_config: PromptConfig,
    should_cite_documents: bool,
) -> Sequence[dict]:
    user_query = _extract_user_query(current_user_message)
    new_task_prompt = build_task_prompt_reminders_v2(
        user_query,
        prompt_config,
        use_language_hint=False,
        should_cite=should_cite_documents,
    )
    last_user_idx = max(
        (i for i, m in enumerate(agent_turn_messages) if m.get("role") == "user"),
        default=-1,
    )
    return [m for i, m in enumerate(agent_turn_messages) if i != last_user_idx] + [
        {"type": "text", "text": new_task_prompt}
    ]


def _extract_user_query(current_user_message: dict) -> str:
    return current_user_message["content"][0]["text"]
