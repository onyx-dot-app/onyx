from unittest.mock import MagicMock
from uuid import uuid4

from onyx.db import tools as tools_mod


def test_create_tool_call_no_commit_sanitizes_fields() -> None:
    mock_session = MagicMock()

    tool_call = tools_mod.create_tool_call_no_commit(
        chat_session_id=uuid4(),
        parent_chat_message_id=1,
        turn_number=0,
        tool_id=1,
        tool_call_id="tc-1",
        tool_call_arguments={"task\x00": "research\ud800 topic"},
        tool_call_response="report\x00 text\udfff here",
        tool_call_tokens=10,
        db_session=mock_session,
        reasoning_tokens="reason\x00ing\ud800",
        generated_images=[{"url": "img\x00.png\udfff"}],
    )

    assert tool_call.tool_call_response == "report text here"
    assert tool_call.reasoning_tokens == "reasoning"
    assert tool_call.tool_call_arguments == {"task": "research topic"}
    assert tool_call.generated_images == [{"url": "img.png"}]
