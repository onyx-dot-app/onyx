from onyx.db.models import Tool
from onyx.tools.models import CapabilityEntry, ToolOptions
from onyx.tools.tool_implementations.sandbox.browser_tool import (
    BrowserTool,
    offers_browser,
)


def _tool(tool_id: int, in_code_tool_id: str | None, enabled: bool = True) -> Tool:
    return Tool(id=tool_id, in_code_tool_id=in_code_tool_id, enabled=enabled)


BROWSER = _tool(7, BrowserTool.__name__)
PYTHON = _tool(8, "PythonTool")


def test_agent_without_the_browser_tool_offers_no_browser() -> None:
    assert not offers_browser([PYTHON], None)


def test_agent_with_the_browser_tool_offers_it_by_default() -> None:
    assert offers_browser([PYTHON, BROWSER], None)


def test_disabled_browser_tool_offers_no_browser() -> None:
    assert not offers_browser([_tool(7, BrowserTool.__name__, enabled=False)], None)


def test_chat_tool_options_turn_the_browser_off_and_on() -> None:
    python_only = ToolOptions(allowed=[CapabilityEntry(tool_id=PYTHON.id)])
    with_browser = ToolOptions(
        allowed=[CapabilityEntry(tool_id=PYTHON.id), CapabilityEntry(tool_id=7)]
    )
    assert not offers_browser([PYTHON, BROWSER], python_only)
    assert offers_browser([PYTHON, BROWSER], with_browser)
