"""Disabling Web Search in chat must cut off open_url's live web access.

OpenURLTool is hidden from the chat tool toggles (chat_selectable=False), so
the frontend always includes it in allowed_tool_ids. When WebSearchTool is
explicitly excluded, the tool stays available but in indexed-only mode: pasted
links are still served from indexed documents, nothing is fetched from the
live internet.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from onyx.agents.runtime import Agent
from onyx.context.search.models import InferenceSection
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage
from onyx.tools.models import ToolContext
from onyx.tools.tool_constructor import should_disable_open_url_web_fetch
from onyx.tools.tool_implementations.open_url.models import FailedFetch
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    WEB_FETCH_DISABLED_REASON,
    OpenURLTool,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient


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
        document_index=MagicMock(),
        user=MagicMock(),
        content_provider=None if web_fetch_disabled else MagicMock(),
        web_fetch_disabled=web_fetch_disabled,
    )


def test_disabled_tool_needs_no_content_provider_and_says_so() -> None:
    tool = _build_tool(web_fetch_disabled=True)
    assert tool._provider is None
    assert "disabled" in tool.description
    assert tool.tool_definition().description == tool.description


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


@pytest.mark.parametrize("web_fetch_disabled", [True, False])
def test_open_url_without_content_reports_an_error(
    web_fetch_disabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = "onyx.tools.tool_implementations.open_url.open_url_tool"
    monkeypatch.setattr(f"{module}.DISABLE_VECTOR_DB", True)
    monkeypatch.setattr(
        f"{module}.get_session_with_current_tenant", lambda: nullcontext(MagicMock())
    )
    tool = _build_tool(web_fetch_disabled=web_fetch_disabled)
    url = "https://example.com"

    def fetch_nothing(
        _urls: list[str], _url_snippet_map: dict[str, str]
    ) -> tuple[list[InferenceSection], list[FailedFetch]]:
        return [], [FailedFetch(url=url, failure_reason="blocked")]

    monkeypatch.setattr(tool, "_fetch_web_content", fetch_nothing)
    call = ToolCall(id="open", name=tool.name, arguments={"urls": [url]})
    run = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[call])),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[tool.bind(lambda: ToolContext())],
    ).start(max_steps=1)
    run.result(timeout=5)
    assert run.wait_for_idle(5)
    [result] = [
        message
        for message in run.snapshot().messages
        if isinstance(message, ToolResultMessage)
    ]
    assert result.is_error
    expected = WEB_FETCH_DISABLED_REASON if web_fetch_disabled else "blocked"
    assert expected in result.text
