from onyx.configs.constants import MessageType
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.tool_implementations.search.search_tool import (
    _expansion_history_with_objective,
)


def test_expansion_uses_current_search_objective_as_final_message() -> None:
    history = [
        ChatMinimalTextMessage(
            message="Original task wording", message_type=MessageType.USER
        )
    ]

    expanded = _expansion_history_with_objective(
        history, ["Find the newly identified service incident"]
    )

    assert expanded[:-1] == history
    assert expanded[-1].message == "Find the newly identified service incident"
    assert expanded[-1].message_type == MessageType.USER
    assert history[-1].message == "Original task wording"


def test_empty_search_objective_keeps_original_history() -> None:
    history = [
        ChatMinimalTextMessage(message="Original task", message_type=MessageType.USER)
    ]
    assert _expansion_history_with_objective(history, ["  "]) is history
