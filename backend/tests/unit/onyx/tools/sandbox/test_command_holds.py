"""A VM command's app requests wait for an approval card only in a call that
a client streams; elsewhere the call holds nothing and the proxy refuses."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.chat.agent import build_chat_agent
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    HarnessSandboxRef,
)
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.sandbox import sandbox_tools
from onyx.tools.tool_implementations.sandbox.command_approvals import (
    CommandApprovals,
)


def _events() -> Generator[ExecCommandResult]:
    yield ExecCommandResult(
        head="ok",
        tail="",
        omitted_chars=0,
        session_id=None,
        exit_code=0,
        completion="exited",
        wall_time_seconds=0.1,
        truncated=False,
    )


@pytest.mark.parametrize("shows", [False, True])
def test_only_a_shown_call_holds_its_command(shows: bool) -> None:
    holds: list[CommandApprovals | None] = []

    def start(hold: CommandApprovals | None) -> Generator[ExecCommandResult]:
        holds.append(hold)
        return _events()

    approvals = MagicMock(spec=CommandApprovals)
    invocation = MagicMock()
    invocation.cancellation.cancelled = False
    with patch.object(sandbox_tools, "CommandApprovals", return_value=approvals):
        sandbox_tools._held_exec_result(
            MagicMock(spec=HarnessSandboxRef, tenant_id="t", session_id=uuid4()),
            invocation,
            ToolContext(shows_command_approvals=shows),
            1000,
            start,
        )

    assert holds == [approvals if shows else None]
    if shows:
        approvals.end.assert_called_once_with(cancelled=False, exited=True)


@pytest.mark.parametrize(
    ("stream", "is_subagent", "shows"),
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_only_a_streamed_root_agent_shows_command_approvals(
    stream: bool, is_subagent: bool, shows: bool
) -> None:
    setup = MagicMock()
    setup.new_msg_req.stream = stream
    with patch("onyx.chat.agent.ChatAgent") as chat_agent:
        build_chat_agent(
            MagicMock(),
            None,
            None,
            setup=setup,
            llm=MagicMock(),
            tools=[],
            inject_memories=False,
            with_subagents=False,
            is_subagent=is_subagent,
        )

    assert chat_agent.call_args.kwargs["shows_command_approvals"] is shows
