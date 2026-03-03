"""Unit tests for WebSearchTool.run(), focusing on query coercion and dispatch."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


def _make_result(title: str = "Title", link: str = "https://example.com") -> WebSearchResult:
    return WebSearchResult(title=title, link=link, snippet="snippet")


def _make_tool(mock_provider: Any) -> WebSearchTool:
    """Instantiate WebSearchTool with all DB/provider deps mocked out."""
    provider_model = MagicMock()
    provider_model.provider_type = "brave"
    provider_model.api_key = MagicMock()
    provider_model.api_key.get_value.return_value = "fake-key"
    provider_model.config = {}

    with (
        patch(
            "onyx.tools.tool_implementations.web_search.web_search_tool.get_session_with_current_tenant"
        ) as mock_session_ctx,
        patch(
            "onyx.tools.tool_implementations.web_search.web_search_tool.fetch_active_web_search_provider",
            return_value=provider_model,
        ),
        patch(
            "onyx.tools.tool_implementations.web_search.web_search_tool.build_search_provider_from_config",
            return_value=mock_provider,
        ),
    ):
        mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)
        tool = WebSearchTool(tool_id=1, emitter=MagicMock())

    return tool


def _run(tool: WebSearchTool, queries: Any) -> list[str]:
    """Call tool.run() and return the list of query strings passed to provider.search."""
    placement = Placement(turn_index=0, tab_index=0)
    override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)
    tool.run(placement=placement, override_kwargs=override_kwargs, queries=queries)
    return [call.args[0] for call in tool._provider.search.call_args_list]  # noqa: SLF001


class TestWebSearchToolRunQueryCoercion:
    def test_list_of_strings_dispatches_each_query(self) -> None:
        """Normal case: list of queries → one search call per query."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_result()]
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)

        dispatched = _run(tool, ["python decorators", "python generators"])

        assert dispatched == ["python decorators", "python generators"]

    def test_bare_string_dispatches_as_single_query(self) -> None:
        """LLM returns a bare string instead of an array — must NOT be split char-by-char."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_result()]
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)

        dispatched = _run(tool, "what is the capital of France")

        assert len(dispatched) == 1
        assert dispatched[0] == "what is the capital of France"

    def test_bare_string_does_not_search_individual_characters(self) -> None:
        """Regression: single-char searches must not occur."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_result()]
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)

        _run(tool, "hi")

        for call in mock_provider.search.call_args_list:
            query_arg = call.args[0]
            assert len(query_arg) > 1, f"Single-character query dispatched: {query_arg!r}"
