from __future__ import annotations

from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import SearchToolDebugDelta
from onyx.tools.models import ToolCallException
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool_implementations.web_search.models import DEFAULT_MAX_RESULTS
from onyx.tools.tool_implementations.web_search.models import WebSearchMode
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    _normalize_queries_input,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


def _make_result(
    title: str = "Title", link: str = "https://example.com"
) -> WebSearchResult:
    return WebSearchResult(title=title, link=link, snippet="snippet")


def _make_tool(
    mock_provider: Any,
    *,
    provider_type: str = "brave",
    provider_name: str = "Brave",
    provider_config: dict[str, str] | None = None,
) -> WebSearchTool:
    """Instantiate WebSearchTool with all DB/provider deps mocked out."""
    provider_model = MagicMock()
    provider_model.name = provider_name
    provider_model.provider_type = provider_type
    provider_model.api_key = MagicMock()
    provider_model.api_key.get_value.return_value = "fake-key"
    provider_model.config = provider_config or {}

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


def _emitted_debug_packets(tool: WebSearchTool) -> list[SearchToolDebugDelta]:
    packets = [call.args[0] for call in tool.emitter.emit.call_args_list]
    return [
        packet.obj
        for packet in packets
        if isinstance(packet.obj, SearchToolDebugDelta)
    ]


def _run(
    tool: WebSearchTool,
    queries: Any,
    *,
    mode: str | None = None,
    default_mode: WebSearchMode = WebSearchMode.LITE,
) -> list[str]:
    """Call tool.run() and return the list of query strings passed to provider.search."""
    placement = Placement(turn_index=0, tab_index=0)
    override_kwargs = WebSearchToolOverrideKwargs(
        starting_citation_num=1,
        default_mode=default_mode,
    )
    kwargs = {"queries": queries}
    if mode is not None:
        kwargs["mode"] = mode
    tool.run(placement=placement, override_kwargs=override_kwargs, **kwargs)
    search_mock = cast(MagicMock, tool._provider.search)  # noqa: SLF001
    return [call.args[0] for call in search_mock.call_args_list]


class TestNormalizeQueriesInput:
    """Unit tests for _normalize_queries_input (coercion + sanitization)."""

    def test_bare_string_returns_single_element_list(self) -> None:
        assert _normalize_queries_input("hello") == ["hello"]

    def test_bare_string_stripped_and_sanitized(self) -> None:
        assert _normalize_queries_input("  hello  ") == ["hello"]
        # Control chars (e.g. null) removed; no space inserted
        assert _normalize_queries_input("hello\x00world") == ["helloworld"]

    def test_empty_string_returns_empty_list(self) -> None:
        assert _normalize_queries_input("") == []
        assert _normalize_queries_input("   ") == []

    def test_list_of_strings_returned_sanitized(self) -> None:
        assert _normalize_queries_input(["a", "b"]) == ["a", "b"]
        # Leading/trailing space stripped; control chars (e.g. tab) removed
        assert _normalize_queries_input(["  a  ", "b\tb"]) == ["a", "bb"]

    def test_list_none_skipped(self) -> None:
        assert _normalize_queries_input(["a", None, "b"]) == ["a", "b"]

    def test_list_non_string_coerced(self) -> None:
        assert _normalize_queries_input([1, "two"]) == ["1", "two"]

    def test_list_whitespace_only_dropped(self) -> None:
        assert _normalize_queries_input(["a", "", "  ", "b"]) == ["a", "b"]

    def test_non_list_non_string_returns_empty_list(self) -> None:
        assert _normalize_queries_input(42) == []
        assert _normalize_queries_input({}) == []


class TestWebSearchToolRunQueryCoercion:
    def test_tool_definition_requires_mode_in_schema(self) -> None:
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_result()]
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)

        parameters = tool.tool_definition()["function"]["parameters"]

        assert "mode" in parameters["properties"]
        assert parameters["properties"]["mode"]["enum"] == [
            "lite",
            "medium",
            "deep",
        ]
        assert "mode" in parameters["required"]

    def test_list_of_strings_dispatches_each_query(self) -> None:
        """Normal case: list of queries → one search call per query."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_result()]
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)

        dispatched = _run(tool, ["python decorators", "python generators"])

        # run_functions_tuples_in_parallel uses a thread pool; call_args_list order is non-deterministic.
        assert sorted(dispatched) == ["python decorators", "python generators"]

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

        dispatched = _run(tool, "hi")
        for query_arg in dispatched:
            assert len(query_arg) > 1, (
                f"Single-character query dispatched: {query_arg!r}"
            )

    def test_control_characters_sanitized_before_dispatch(self) -> None:
        """Queries with control chars have those chars removed before dispatch."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_result()]
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)

        dispatched = _run(tool, ["foo\x00bar", "baz\tbaz"])

        # run_functions_tuples_in_parallel uses a thread pool; call_args_list is in
        # execution order, not submission order, so compare in sorted order.
        assert sorted(dispatched) == ["bazbaz", "foobar"]

    def test_all_empty_or_whitespace_raises_tool_call_exception(self) -> None:
        """When normalization yields no valid queries, run() raises ToolCallException."""
        mock_provider = MagicMock()
        mock_provider.supports_site_filter = False
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        with pytest.raises(ToolCallException) as exc_info:
            tool.run(
                placement=placement,
                override_kwargs=override_kwargs,
                queries="   ",
            )

        assert "No valid" in str(exc_info.value)
        cast(MagicMock, mock_provider.search).assert_not_called()

    def test_explicit_deep_mode_passed_to_batch_provider(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        mock_provider.search_batch.return_value = [_make_result()]
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=["q1", "q2"],
            mode="deep",
        )

        mock_provider.search_batch.assert_called_once_with(
            ["q1", "q2"],
            mode=WebSearchMode.DEEP,
            max_results=DEFAULT_MAX_RESULTS,
        )
        cast(MagicMock, mock_provider.search).assert_not_called()

    def test_explicit_medium_mode_passed_to_batch_provider(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        mock_provider.search_batch.return_value = [_make_result()]
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=["q1", "q2"],
            mode="medium",
        )

        mock_provider.search_batch.assert_called_once_with(
            ["q1", "q2"],
            mode=WebSearchMode.MEDIUM,
            max_results=DEFAULT_MAX_RESULTS,
        )
        cast(MagicMock, mock_provider.search).assert_not_called()

    def test_missing_mode_defaults_to_lite_for_chat(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        mock_provider.search_batch.return_value = [_make_result()]
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=["q1"],
        )

        assert mock_provider.search_batch.call_args.kwargs["mode"] == WebSearchMode.LITE

    def test_missing_mode_uses_override_default_for_deep_research(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        mock_provider.search_batch.return_value = [_make_result()]
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(
            starting_citation_num=1,
            default_mode=WebSearchMode.DEEP,
        )

        tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=["q1"],
        )

        assert mock_provider.search_batch.call_args.kwargs["mode"] == WebSearchMode.DEEP

    def test_invalid_mode_raises_tool_call_exception(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        with pytest.raises(ToolCallException, match="Invalid web search mode"):
            tool.run(
                placement=placement,
                override_kwargs=override_kwargs,
                queries=["q1"],
                mode="research",
            )

    def test_successful_batch_search_emits_debug_packet(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        mock_provider.search_batch.return_value = [
            _make_result(title="First", link="https://example.com/first"),
            _make_result(title="Second", link="https://example.com/second"),
        ]
        tool = _make_tool(
            mock_provider,
            provider_type="glomi",
            provider_name="Glomi Search",
            provider_config={"channel": "tavily", "base_url": "https://hidden"},
        )
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=["q1", "q2"],
            mode="deep",
        )

        debug_packets = _emitted_debug_packets(tool)
        assert len(debug_packets) == 1
        debug = debug_packets[0]
        assert debug.provider_type == "glomi"
        assert debug.provider_name == "Glomi Search"
        assert debug.mode == "deep"
        assert debug.channel == "tavily"
        assert debug.queries == ["q1", "q2"]
        assert debug.duration_ms >= 0
        assert debug.result_count == 2
        assert [result.url for result in debug.results] == [
            "https://example.com/first",
            "https://example.com/second",
        ]
        assert debug.failed_queries == {}
        assert debug.error is None

    def test_partial_query_failure_emits_failed_queries_debug(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = False

        def _search(query: str) -> list[WebSearchResult]:
            if query == "bad":
                raise RuntimeError("provider timeout")
            return [_make_result(title=query, link=f"https://example.com/{query}")]

        mock_provider.search.side_effect = _search
        tool = _make_tool(mock_provider)
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=["good", "bad"],
            mode="lite",
        )

        debug = _emitted_debug_packets(tool)[0]
        assert debug.provider_type == "brave"
        assert debug.mode == "lite"
        assert debug.failed_queries == {"bad": "provider timeout"}
        assert debug.error is None
        assert debug.result_count == 1

    def test_batch_failure_emits_error_debug_before_tool_exception(self) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_batch_queries = True
        mock_provider.search_batch.side_effect = RuntimeError("gateway down")
        tool = _make_tool(
            mock_provider,
            provider_type="glomi",
            provider_name="Glomi Search",
            provider_config={"channel": "tavily"},
        )
        placement = Placement(turn_index=0, tab_index=0)
        override_kwargs = WebSearchToolOverrideKwargs(starting_citation_num=1)

        with pytest.raises(ToolCallException, match="Web search batch failed"):
            tool.run(
                placement=placement,
                override_kwargs=override_kwargs,
                queries=["q1"],
                mode="deep",
            )

        debug = _emitted_debug_packets(tool)[0]
        assert debug.provider_type == "glomi"
        assert debug.mode == "deep"
        assert debug.channel == "tavily"
        assert debug.queries == ["q1"]
        assert debug.result_count == 0
        assert debug.results == []
        assert debug.failed_queries == {}
        assert debug.error == "gateway down"
