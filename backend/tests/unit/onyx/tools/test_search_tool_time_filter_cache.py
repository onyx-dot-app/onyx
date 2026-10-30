from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from onyx.context.search.models import DocumentTimeField, TimeFilter
from onyx.llm.models import ToolResultMessage
from onyx.tools.tool_implementations.search.models import (
    SearchContext,
    SearchPlanningResult,
)
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
    update_search_context,
)


@pytest.mark.parametrize("restricted", [True, False])
def test_time_filter_is_reused_after_completed_search(restricted: bool) -> None:
    tool = SearchTool.__new__(SearchTool)
    tool.llm = MagicMock()
    tool.auto_detect_filters = True
    context = SearchContext(scope_decision_settled=True)
    decided = (
        TimeFilter(
            field=DocumentTimeField.UPDATED_AT,
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        if restricted
        else None
    )
    with patch(
        "onyx.tools.tool_implementations.search.search_tool.decide_time_filter",
        return_value=decided,
    ) as decide:
        first = tool._expand_queries_and_decide_scope(
            skip_query_expansion=True,
            search_context=context,
            message_history=[],
            user_info=None,
            memories=[],
            candidate_sources=[],
            llm_queries=[],
        )
        context = update_search_context(
            context,
            [
                ToolResultMessage(
                    tool_call_id="search",
                    tool_name="internal_search",
                    content="",
                    metadata=SearchPlanningResult(
                        original_queries=("query",),
                        searched_sources=(),
                        time_filter=first.time_filter,
                        time_filter_computed=first.time_filter_computed,
                    ),
                )
            ],
        )
        second = tool._expand_queries_and_decide_scope(
            skip_query_expansion=True,
            search_context=context,
            message_history=[],
            user_info=None,
            memories=[],
            candidate_sources=[],
            llm_queries=[],
        )
    decide.assert_called_once()
    assert first.time_filter == second.time_filter == decided
    assert context.time_filter_computed
    assert not second.time_filter_computed


def test_time_filter_skipped_when_auto_detect_disabled() -> None:
    tool = SearchTool.__new__(SearchTool)
    tool.llm = MagicMock()
    tool.auto_detect_filters = False
    with patch(
        "onyx.tools.tool_implementations.search.search_tool.decide_time_filter"
    ) as decide:
        result = tool._expand_queries_and_decide_scope(
            skip_query_expansion=True,
            search_context=SearchContext(),
            message_history=[],
            user_info=None,
            memories=[],
            candidate_sources=[],
            llm_queries=[],
        )
    decide.assert_not_called()
    assert result.time_filter is None
    assert not result.time_filter_computed
