from unittest.mock import MagicMock, patch

from onyx.tools.tool_implementations.search import search_tool
from onyx.tools.tool_implementations.search.models import SearchContext
from onyx.tools.tool_implementations.search.search_tool import SearchTool


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
            search_context=SearchContext(),
            message_history=[],
            user_info=None,
            memories=[],
            candidate_sources=[],
            llm_queries=[],
        )

    resolver.assert_not_called()
    for operation in (semantic, keyword, scope, time_filter):
        assert operation.call_args.args[1] is primary
