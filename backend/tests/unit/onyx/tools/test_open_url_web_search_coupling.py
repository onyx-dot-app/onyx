"""OpenURLTool must not survive a message that explicitly excludes WebSearchTool.

OpenURLTool is hidden from the chat tool toggles (chat_selectable=False), so the
frontend always includes it in allowed_tool_ids. Without the coupling in
should_exclude_open_url_tool, disabling "Web Search" in chat still leaves the
model with internet access via open_url.
"""

from unittest.mock import MagicMock

from onyx.tools.tool_constructor import should_exclude_open_url_tool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


def _tool(tool_id: int, in_code_tool_id: str | None) -> MagicMock:
    tool = MagicMock()
    tool.id = tool_id
    tool.in_code_tool_id = in_code_tool_id
    return tool


WEB_SEARCH = _tool(1, WebSearchTool.__name__)
OPEN_URL = _tool(2, OpenURLTool.__name__)
SEARCH = _tool(3, "SearchTool")


def test_excluded_when_web_search_not_in_allowed_list() -> None:
    assert (
        should_exclude_open_url_tool(
            [WEB_SEARCH, OPEN_URL, SEARCH], allowed_tool_ids=[OPEN_URL.id, SEARCH.id]
        )
        is True
    )


def test_not_excluded_when_web_search_allowed() -> None:
    assert (
        should_exclude_open_url_tool(
            [WEB_SEARCH, OPEN_URL], allowed_tool_ids=[WEB_SEARCH.id, OPEN_URL.id]
        )
        is False
    )


def test_not_excluded_without_allowlist() -> None:
    assert (
        should_exclude_open_url_tool([WEB_SEARCH, OPEN_URL], allowed_tool_ids=None)
        is False
    )


def test_not_excluded_when_persona_has_no_web_search() -> None:
    # An agent configured with open_url but no web_search keeps open_url; there
    # is no web-search toggle whose state could express "no internet" intent.
    assert (
        should_exclude_open_url_tool([OPEN_URL, SEARCH], allowed_tool_ids=[OPEN_URL.id])
        is False
    )
