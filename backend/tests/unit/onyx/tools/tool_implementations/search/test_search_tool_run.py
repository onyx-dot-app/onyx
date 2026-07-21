from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.search.constants import KEYWORD_ONLY_HYBRID_ALPHA
from onyx.tools.tool_implementations.search.constants import LLM_SEMANTIC_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.constants import MODEL_KEYWORD_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.constants import MODEL_SEMANTIC_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.constants import ORIGINAL_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.search.turn_state import SearchToolTurnState

MODULE = "onyx.tools.tool_implementations.search.search_tool"


def _make_tool(
    user_selected_filters: BaseFilters | None = None,
    turn_state: SearchToolTurnState | None = None,
) -> SearchTool:
    """Instantiate SearchTool with non-DB deps mocked; DB/LLM calls are patched in _run."""
    return SearchTool(
        tool_id=1,
        emitter=MagicMock(),
        user=MagicMock(is_anonymous=False),
        persona_search_info=MagicMock(document_set_names=[]),
        llm=MagicMock(),
        document_index=MagicMock(),
        user_selected_filters=user_selected_filters,
        project_id_filter=None,
        enable_slack_search=False,
        turn_state=turn_state,
    )


def _run(
    tool: SearchTool,
    *,
    # str is allowed to exercise the bare-string coercion the tool performs
    semantic_queries: list[str] | str | None = None,
    keyword_queries: list[str] | str | None = None,
    skip_query_expansion: bool = False,
    rephrase_mock: MagicMock | None = None,
) -> tuple[MagicMock, MagicMock, str]:
    """Run tool.run() with all DB/LLM deps mocked.

    Returns (search_pipeline mock, rrf mock, llm_facing_response). search_pipeline
    returns no chunks, so run() takes the empty-results early return after the
    fan-out — which still exercises query grouping, weights, and payload fields.
    """
    mock_search_pipeline = MagicMock(return_value=[])
    mock_rrf = MagicMock(return_value=[])
    rephrase = (
        rephrase_mock
        if rephrase_mock is not None
        else MagicMock(return_value="rephrased query")
    )

    def run_sequential(
        functions_with_args: list[tuple[Any, tuple]], **_: Any
    ) -> list[Any]:
        # Deterministic ordering so mock call order matches submission order.
        return [func(*args) for func, args in functions_with_args]

    llm_kwargs: dict[str, Any] = {}
    if semantic_queries is not None:
        llm_kwargs["semantic_queries"] = semantic_queries
    if keyword_queries is not None:
        llm_kwargs["keyword_queries"] = keyword_queries
    with (
        patch(f"{MODULE}.get_session_with_current_tenant") as mock_session_ctx,
        patch(f"{MODULE}.build_access_filters_for_user", return_value=[]),
        patch(f"{MODULE}.get_current_search_settings", return_value=MagicMock()),
        patch(f"{MODULE}.EmbeddingModel"),
        patch(f"{MODULE}.get_federated_retrieval_functions", return_value=[]),
        patch(f"{MODULE}.semantic_query_rephrase", rephrase),
        patch(f"{MODULE}.weighted_reciprocal_rank_fusion", mock_rrf),
        patch(f"{MODULE}.merge_individual_chunks", return_value=[]),
        patch(f"{MODULE}.search_pipeline", mock_search_pipeline),
        patch(f"{MODULE}.run_functions_tuples_in_parallel", run_sequential),
    ):
        mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)
        response = tool.run(
            placement=Placement(turn_index=0, tab_index=0),
            override_kwargs=SearchToolOverrideKwargs(
                starting_citation_num=1,
                original_query="resolve the ticket",
                message_history=[
                    ChatMinimalTextMessage(
                        message="resolve the ticket",
                        message_type=MessageType.USER,
                    )
                ],
                skip_query_expansion=skip_query_expansion,
            ),
            **llm_kwargs,
        )
    return mock_search_pipeline, mock_rrf, response.llm_facing_response


def _requests_sent(mock_search_pipeline: MagicMock) -> list[Any]:
    return [
        call.kwargs["chunk_search_request"]
        for call in mock_search_pipeline.call_args_list
    ]


def test_missing_both_query_lists_raises() -> None:
    tool = _make_tool()
    with pytest.raises(ToolCallException):
        _run(tool)


def test_empty_query_lists_raise() -> None:
    tool = _make_tool()
    with pytest.raises(ToolCallException):
        _run(tool, semantic_queries=[], keyword_queries=["  "])


def test_one_list_is_enough() -> None:
    tool = _make_tool()
    mock_search_pipeline, _, _ = _run(tool, keyword_queries=["onboarding docs"])
    queries = [req.query for req in _requests_sent(mock_search_pipeline)]
    assert "onboarding docs" in queries


def test_keyword_queries_run_pure_keyword_and_semantic_run_hybrid() -> None:
    tool = _make_tool()
    mock_search_pipeline, _, _ = _run(
        tool,
        semantic_queries=["how do I resolve a ticket?"],
        keyword_queries=["ticket resolution"],
    )

    requests_by_query = {req.query: req for req in _requests_sent(mock_search_pipeline)}
    assert requests_by_query["how do I resolve a ticket?"].hybrid_alpha is None, (
        "semantic queries should use the default hybrid search"
    )
    assert (
        requests_by_query["ticket resolution"].hybrid_alpha == KEYWORD_ONLY_HYBRID_ALPHA
    ), "keyword queries should route down the pure keyword (BM25) path"
    # The automatic rephrase also runs as a semantic (hybrid) query.
    assert requests_by_query["rephrased query"].hybrid_alpha is None


def test_rrf_weights_per_query_group() -> None:
    tool = _make_tool()
    mock_search_pipeline, mock_rrf, _ = _run(
        tool,
        semantic_queries=["how do I resolve a ticket?"],
        keyword_queries=["ticket resolution"],
    )

    queries = [req.query for req in _requests_sent(mock_search_pipeline)]
    weights = mock_rrf.call_args.kwargs["weights"]
    weight_by_query = dict(zip(queries, weights))

    assert weight_by_query["rephrased query"] == LLM_SEMANTIC_QUERY_WEIGHT
    assert weight_by_query["how do I resolve a ticket?"] == MODEL_SEMANTIC_QUERY_WEIGHT
    assert weight_by_query["ticket resolution"] == MODEL_KEYWORD_QUERY_WEIGHT
    assert weight_by_query["resolve the ticket"] == ORIGINAL_QUERY_WEIGHT


def test_search_query_id_increments_and_is_in_payload() -> None:
    tool = _make_tool()
    _, _, first_response = _run(tool, semantic_queries=["first search"])
    _, _, second_response = _run(
        tool, semantic_queries=["second search"], skip_query_expansion=True
    )

    assert json.loads(first_response)["search_query_id"] == 1
    assert json.loads(second_response)["search_query_id"] == 2


def test_automatic_expansion_surfaced_only_when_rephrase_runs() -> None:
    tool = _make_tool()
    _, _, first_response = _run(tool, semantic_queries=["first search"])
    assert (
        json.loads(first_response)["automatic_semantic_expansion"] == "rephrased query"
    )

    _, _, second_response = _run(
        tool, semantic_queries=["second search"], skip_query_expansion=True
    )
    assert "automatic_semantic_expansion" not in json.loads(second_response)


def test_rephrase_skipped_on_repeat_calls() -> None:
    tool = _make_tool()
    rephrase_mock = MagicMock(return_value="rephrased query")

    _run(tool, semantic_queries=["first"], rephrase_mock=rephrase_mock)
    _run(
        tool,
        semantic_queries=["second"],
        skip_query_expansion=True,
        rephrase_mock=rephrase_mock,
    )

    assert rephrase_mock.call_count == 1


def test_rephrase_computed_once_even_without_skip_flag() -> None:
    """Parallel first-cycle calls both run without skip_query_expansion; the
    shared turn state makes the rephrase run only once."""
    turn_state = SearchToolTurnState()
    tool = _make_tool(turn_state=turn_state)
    rephrase_mock = MagicMock(return_value="rephrased query")

    _run(tool, semantic_queries=["first"], rephrase_mock=rephrase_mock)
    _run(tool, semantic_queries=["second"], rephrase_mock=rephrase_mock)

    assert rephrase_mock.call_count == 1


def test_user_selected_filters_still_apply() -> None:
    restriction = [DocumentSource.CONFLUENCE, DocumentSource.GITHUB]
    tool = _make_tool(BaseFilters(source_type=restriction))
    mock_search_pipeline, _, _ = _run(tool, semantic_queries=["find the doc"])

    requests = _requests_sent(mock_search_pipeline)
    assert requests, "search_pipeline was never called"
    for req in requests:
        assert req.user_selected_filters is not None
        assert req.user_selected_filters.source_type == restriction


def test_bare_string_queries_are_coerced() -> None:
    tool = _make_tool()
    mock_search_pipeline, _, _ = _run(
        tool,
        semantic_queries="who owns the runbook?",
    )
    queries = [req.query for req in _requests_sent(mock_search_pipeline)]
    assert "who owns the runbook?" in queries
