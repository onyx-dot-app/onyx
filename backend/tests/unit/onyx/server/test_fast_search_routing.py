from unittest.mock import MagicMock, patch

import pytest

from onyx.tools.tool_implementations.search.search_tool import SearchTool


@pytest.mark.parametrize("configured", [False, True])
def test_search_tool_resolves_selection_client_once_on_first_access(
    configured: bool,
) -> None:
    fallback, fast = MagicMock(), MagicMock()
    resolver = MagicMock(return_value=fast if configured else fallback)
    tool = SearchTool(
        tool_id=1,
        user=MagicMock(),
        persona_search_info=MagicMock(),
        llm=fallback,
        document_index=MagicMock(),
        user_selected_filters=None,
        project_id_filter=None,
        selection_llm_factory=resolver,
    )

    resolver.assert_not_called()
    expected_llm = fast if configured else fallback
    assert tool.llm is fallback
    resolver.assert_not_called()
    assert tool.selection_llm is expected_llm
    assert tool.selection_llm is expected_llm
    assert tool.enforce_selection_input_budget is configured
    resolver.assert_called_once_with()


def test_search_tool_falls_back_to_primary_when_selection_unavailable() -> None:
    primary = MagicMock()
    resolver = MagicMock(side_effect=ValueError("utility budget exceeded"))
    tool = SearchTool(
        tool_id=1,
        user=MagicMock(),
        persona_search_info=MagicMock(),
        llm=primary,
        document_index=MagicMock(),
        user_selected_filters=None,
        project_id_filter=None,
        selection_llm_factory=resolver,
    )

    assert tool.tool_definition().name == "internal_search"
    _ = tool.llm
    resolver.assert_not_called()
    assert tool.selection_llm is primary
    assert tool.enforce_selection_input_budget is False


def test_search_rewrites_and_filters_never_resolve_selection_client() -> None:
    primary = MagicMock()
    resolver = MagicMock(side_effect=ValueError("selection model unavailable"))
    tool = SearchTool(
        tool_id=1,
        user=MagicMock(),
        persona_search_info=MagicMock(),
        llm=primary,
        document_index=MagicMock(),
        user_selected_filters=None,
        project_id_filter=None,
        selection_llm_factory=resolver,
    )
    from onyx.tools.tool_implementations.search import search_tool

    with (
        patch.object(
            search_tool, "semantic_query_rephrase", return_value="query"
        ) as semantic,
        patch.object(
            search_tool, "keyword_query_expansion", return_value=["keyword"]
        ) as keyword,
        patch.object(search_tool, "decide_search_scope", return_value=None) as scope,
        patch.object(
            search_tool, "decide_time_filter", return_value=None
        ) as time_filter,
        patch.object(
            search_tool,
            "run_functions_tuples_in_parallel",
            side_effect=lambda jobs: [function(*args) for function, args in jobs],
        ),
    ):
        tool._expand_queries_and_decide_scope(
            skip_query_expansion=False,
            message_history=[],
            user_info=None,
            memories=[],
            decide_args=([], primary, [], [], []),
        )

    resolver.assert_not_called()
    for operation in (semantic, keyword, scope, time_filter):
        assert operation.call_args.args[1] is primary
