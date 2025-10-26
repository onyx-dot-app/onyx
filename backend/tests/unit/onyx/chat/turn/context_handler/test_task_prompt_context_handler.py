from collections.abc import Sequence
from typing import Any

from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler.task_prompt import update_task_prompt


def test_task_prompt_handler_with_no_user_messages() -> None:
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )
    current_user_message = {
        "role": "user",
        "content": [{"type": "text", "text": "Current query"}],
    }
    agent_turn_messages: Sequence[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Assistant message 1"}],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Assistant message 2"}],
        },
    ]

    result = update_task_prompt(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    assert len(result) == 3
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "user"


def test_task_prompt_handler_basic() -> None:
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt=task_prompt,
        datetime_aware=False,
    )
    current_user_message = {
        "role": "user",
        "content": [{"type": "text", "text": "Query"}],
    }
    agent_turn_messages: Sequence[dict[str, Any]] = [
        {"role": "system", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries": ["hi"]}',
                        "name": "internal_search",
                    },
                    "id": "call_1",
                    "type": "function",
                }
            ],
        },
        {"role": "tool", "content": "Tool message 1", "tool_call_id": "call_1"},
        {"role": "user", "content": [{"type": "text", "text": "reminder!"}]},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries": ["hi"]}',
                        "name": "internal_search",
                    },
                    "id": "call_1",
                    "type": "function",
                }
            ],
        },
        {"role": "tool", "content": "Tool message 1", "tool_call_id": "call_1"},
    ]

    result = update_task_prompt(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    assert len(result) == 6
    assert result[0]["role"] == "system"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "tool"
    assert result[3]["role"] == "assistant"
    assert result[4]["role"] == "tool"
    assert result[5]["role"] == "user"
    assert task_prompt in result[5]["content"]
