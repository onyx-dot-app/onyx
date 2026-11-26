from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.model_capabilities import ToolFamily
from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandbox,
    HarnessSandboxError,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxRef,
    session_workspace,
)
from onyx.tools.models import ToolCallException
from onyx.tools.ordering import tool_order
from onyx.tools.tool_implementations.sandbox.browser_tools import (
    BROWSER_TOOLS,
    BrowserActTool,
    BrowserNavigateTool,
    BrowserOpenTool,
    BrowserSnapshotTool,
    with_browser_tools,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import SANDBOX_TOOLS
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


def _turn(result: dict[str, JsonValue] | Exception) -> tuple[MagicMock, MagicMock]:
    ref = HarnessSandboxRef(tenant_id="public", sandbox_id=uuid4(), session_id=uuid4())
    sandbox = MagicMock(spec=HarnessSandbox)
    if isinstance(result, Exception):
        sandbox.browser_call.side_effect = result
    else:
        sandbox.browser_call.return_value = result
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]
    turn.start_call.return_value = ref
    turn.sandbox = sandbox
    return turn, sandbox


def _invocation(arguments: dict[str, JsonValue]) -> ToolInvocation:
    return ToolInvocation(
        call_id="call",
        arguments=arguments,
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )


def _mock_turn(family: ToolFamily) -> MagicMock:
    turn = MagicMock(spec=SandboxTurn)
    turn.vm_chat_files = []
    turn.shell = SHELL_SHAPES[family]
    return turn


@pytest.mark.parametrize("family", list(ToolFamily))
@pytest.mark.parametrize("browser", [True, False])
def test_the_browser_setting_gates_the_browser_tools(
    family: ToolFamily, browser: bool
) -> None:
    sandbox = SANDBOX_TOOLS[family]
    tools = with_browser_tools(sandbox.tools, browser=browser)
    assert (set(BROWSER_TOOLS) <= set(tools)) is browser
    assert not set(tools) - set(sandbox.tools) - set(BROWSER_TOOLS)
    names = [tool.tool_name(sandbox.shell) for tool in tools]
    assert len(names) == len(set(names))
    # The web panel opens itself on a call of this name.
    assert ("browser_open" in names) is browser
    # The browser tools rank after the family's sandbox tools.
    turn = _mock_turn(family)
    ordered = sorted((tool(turn) for tool in tools), key=tool_order)
    assert [type(tool) for tool in ordered[: len(sandbox.tools)]] == sorted(
        sandbox.tools, key=lambda tool: tool_order(tool(turn))
    )


def test_every_browser_tool_has_a_strict_definition_and_browser_open_guides_use() -> (
    None
):
    turn = _mock_turn(ToolFamily.OPENAI)
    for tool in BROWSER_TOOLS:
        definition = tool(turn).tool_definition()
        assert definition.name == tool.NAME
    # The usage guidance is in browser_open's description, not the system
    # prompt.
    description = BrowserOpenTool(turn).description
    assert "take control" in description
    assert "`new_tab` true" in description
    assert "sign in" in description


def test_act_sends_the_service_params_with_session_paths() -> None:
    turn, sandbox = _turn({"tab": {"id": "t1"}})
    ref = turn.start_call.return_value
    result = BrowserActTool(turn)._run(
        _invocation(
            {
                "action": "upload",
                "ref": "e2_5",
                "paths": [f"{session_workspace(ref.session_id)}/a.pdf", "b/c.png"],
                "modifiers": None,
                "timeout_ms": 999_999,
            }
        ),
        MagicMock(),
    )

    sandbox.browser_call.assert_called_once()
    args, kwargs = sandbox.browser_call.call_args
    assert args == (
        ref,
        "act",
        {
            "action": "upload",
            "ref": "e2_5",
            "paths": ["a.pdf", "b/c.png"],
            "timeoutMs": 60_000,
        },
    )
    assert kwargs["timeout_seconds"] > 60
    assert result.content == '{"tab":{"id":"t1"}}'


def test_open_and_snapshot_map_their_arguments() -> None:
    turn, sandbox = _turn({"tab": {"id": "t2"}})
    BrowserOpenTool(turn)._run(
        _invocation({"url": "example.com", "new_tab": True}), MagicMock()
    )
    assert sandbox.browser_call.call_args.args[1:] == (
        "open",
        {"url": "example.com", "newTab": True},
    )

    turn, sandbox = _turn({"tab": {"id": "t2"}, "text": "Title: Example\n- link"})
    result = BrowserSnapshotTool(turn)._run(_invocation({}), MagicMock())
    assert result.content == '{"tab":{"id":"t2"}}\nTitle: Example\n- link'


def test_a_refused_call_and_bad_arguments_become_tool_errors() -> None:
    message = "A human controls this tab. Open a new tab."
    turn, _ = _turn(HarnessSandboxError(message))
    with pytest.raises(ToolCallException) as raised:
        BrowserActTool(turn)._run(
            _invocation({"action": "click", "ref": "e1_1"}), MagicMock()
        )
    assert raised.value.llm_facing_message == message

    turn, sandbox = _turn({})
    with pytest.raises(ToolCallException):
        BrowserNavigateTool(turn)._run(
            _invocation({"url": "a.com", "history": "back"}), MagicMock()
        )
    with pytest.raises(ToolCallException):
        BrowserActTool(turn)._run(
            _invocation({"action": "upload", "paths": ["../escape.txt"]}), MagicMock()
        )
    sandbox.browser_call.assert_not_called()
