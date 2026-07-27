"""Disabling Web Search in chat must cut off open_url's live web access.

OpenURLTool is hidden from the chat tool toggles (chat_selectable=False), so
the frontend always includes it in allowed_tool_ids. When WebSearchTool is
explicitly excluded, the tool stays available but in indexed-only mode: pasted
links are still served from indexed documents, nothing is fetched from the
live internet.
"""

from unittest.mock import MagicMock

from onyx.tools.tool_constructor import should_disable_open_url_web_fetch
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    WEB_FETCH_DISABLED_REASON,
    OpenURLTool,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


def _tool(tool_id: int, in_code_tool_id: str | None) -> MagicMock:
    tool = MagicMock()
    tool.id = tool_id
    tool.in_code_tool_id = in_code_tool_id
    return tool


WEB_SEARCH = _tool(1, WebSearchTool.__name__)
OPEN_URL = _tool(2, OpenURLTool.__name__)
SEARCH = _tool(3, "SearchTool")


def test_disabled_when_web_search_not_in_allowed_list() -> None:
    assert (
        should_disable_open_url_web_fetch(
            [WEB_SEARCH, OPEN_URL, SEARCH], allowed_tool_ids=[OPEN_URL.id, SEARCH.id]
        )
        is True
    )


def test_not_disabled_when_web_search_allowed() -> None:
    assert (
        should_disable_open_url_web_fetch(
            [WEB_SEARCH, OPEN_URL], allowed_tool_ids=[WEB_SEARCH.id, OPEN_URL.id]
        )
        is False
    )


def test_not_disabled_without_allowlist() -> None:
    assert (
        should_disable_open_url_web_fetch([WEB_SEARCH, OPEN_URL], allowed_tool_ids=None)
        is False
    )


def test_not_disabled_when_persona_has_no_web_search() -> None:
    # An agent configured with open_url but no web_search tool keeps full
    # open_url behavior; there is no web-search toggle whose state could
    # express "no internet" intent.
    assert (
        should_disable_open_url_web_fetch(
            [OPEN_URL, SEARCH], allowed_tool_ids=[OPEN_URL.id]
        )
        is False
    )


def _build_tool(web_fetch_disabled: bool) -> OpenURLTool:
    # No content_provider passed in disabled mode: the constructor must not
    # try to resolve one (and must not raise when none is configured).
    return OpenURLTool(
        tool_id=2,
        emitter=MagicMock(),
        document_index=MagicMock(),
        user=MagicMock(),
        content_provider=None if web_fetch_disabled else MagicMock(),
        web_fetch_disabled=web_fetch_disabled,
    )


def test_disabled_tool_needs_no_content_provider_and_says_so() -> None:
    tool = _build_tool(web_fetch_disabled=True)
    assert tool._provider is None
    assert "disabled" in tool.description
    assert tool.tool_definition()["function"]["description"] == tool.description


def test_enabled_tool_keeps_default_description() -> None:
    tool = _build_tool(web_fetch_disabled=False)
    assert tool.description == OpenURLTool.DESCRIPTION


def test_fetch_web_content_guard_when_provider_missing() -> None:
    tool = _build_tool(web_fetch_disabled=True)
    sections, failures = tool._fetch_web_content(
        ["https://example.com"], url_snippet_map={}
    )
    assert sections == []
    assert [f.url for f in failures] == ["https://example.com"]
    assert failures[0].failure_reason == WEB_FETCH_DISABLED_REASON
