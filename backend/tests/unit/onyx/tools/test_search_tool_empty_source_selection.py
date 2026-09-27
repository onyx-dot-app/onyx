from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from onyx.context.search.models import BaseFilters, SearchDocsResponse
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def _make_tool(
    user_selected_filters: BaseFilters | None,
    project_id_filter: int | None = None,
) -> SearchTool:
    """A SearchTool with only the state the empty-selection guard reads,
    avoiding the heavy __init__ (DB, emitter, etc.)."""
    tool = SearchTool.__new__(SearchTool)
    tool.user_selected_filters = user_selected_filters
    tool.project_id_filter = project_id_filter
    return tool


def test_empty_source_selection_returns_no_results() -> None:
    """An explicitly empty source list means "search nothing", not "no filter"."""
    tool = _make_tool(BaseFilters(source_type=[]))

    response = tool.run(
        placement=MagicMock(), override_kwargs=MagicMock(), queries=["q"]
    )

    assert isinstance(response.rich_response, SearchDocsResponse)
    assert response.rich_response.search_docs == []
    assert response.rich_response.citation_mapping == {}


@pytest.mark.parametrize(
    "filters",
    [None, BaseFilters(source_type=None), BaseFilters(document_set=["a set"])],
)
def test_absent_source_filter_still_searches(filters: BaseFilters | None) -> None:
    """`None` keeps its meaning of "no source filter": the search proceeds."""
    tool = _make_tool(filters)

    sentinel = RuntimeError("reached the search body")
    with patch(
        "onyx.tools.tool_implementations.search.search_tool."
        "get_session_with_current_tenant",
        side_effect=sentinel,
    ):
        with pytest.raises(RuntimeError, match="reached the search body"):
            tool.run(placement=MagicMock(), override_kwargs=MagicMock(), queries=["q"])


def test_project_mode_ignores_empty_source_selection() -> None:
    """Project searches ignore user filters, so the guard must not fire."""
    tool = _make_tool(BaseFilters(source_type=[]), project_id_filter=42)

    sentinel = RuntimeError("reached the search body")
    with patch(
        "onyx.tools.tool_implementations.search.search_tool."
        "get_session_with_current_tenant",
        side_effect=sentinel,
    ):
        with pytest.raises(RuntimeError, match="reached the search body"):
            tool.run(placement=MagicMock(), override_kwargs=MagicMock(), queries=["q"])


def test_malformed_call_raises_despite_empty_selection() -> None:
    """Argument validation outranks the short-circuit: no silent success."""
    tool = _make_tool(BaseFilters(source_type=[]))

    with pytest.raises(ToolCallException):
        tool.run(placement=MagicMock(), override_kwargs=MagicMock())
