"""The run store of a turn saves explicit tool options, so a turn that the
server starts later (an agent host) matches the parked agents of a request
that sent none."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.chat.execution import bind_run_store
from onyx.tools.models import CapabilityEntry, ToolOptions

MODULE = "onyx.chat.execution"


@pytest.mark.parametrize(
    "sent,saved",
    [
        (None, ToolOptions()),
        (
            ToolOptions(allowed=[CapabilityEntry(tool_id=3)]),
            ToolOptions(allowed=[CapabilityEntry(tool_id=3)]),
        ),
    ],
)
def test_the_run_store_saves_explicit_tool_options(
    sent: ToolOptions | None, saved: ToolOptions
) -> None:
    chat_session_id = uuid4()
    setup = MagicMock(chat_session_id=chat_session_id)
    setup.new_msg_req.tool_options = sent
    with (
        patch(
            f"{MODULE}.load_chat_branch",
            return_value=MagicMock(chat_session_id=chat_session_id, message_ids=[1]),
        ),
        patch(f"{MODULE}.ChatRunStore") as store_class,
        patch(f"{MODULE}.get_cache_backend"),
        patch(f"{MODULE}.get_current_tenant_id", return_value="public"),
    ):
        bind_run_store(
            setup,
            MagicMock(),
            response_id=1,
            llm=MagicMock(),
            tools=[],
            coordinator=MagicMock(),
            follow_up_steps=3,
            root_response=None,
            on_child_released=None,
        )

    assert store_class.call_args.kwargs["tool_options"] == saved
