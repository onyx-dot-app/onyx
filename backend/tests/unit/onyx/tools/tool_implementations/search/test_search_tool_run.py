from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import SearchTool

MODULE = "onyx.tools.tool_implementations.search.search_tool"


def _make_tool() -> SearchTool:
    """Instantiate SearchTool with non-DB deps mocked; DB/LLM calls are patched in _run."""
    return SearchTool(
        tool_id=1,
        emitter=MagicMock(),
        user=MagicMock(is_anonymous=False),
        persona_search_info=MagicMock(document_set_names=[]),
        llm=MagicMock(),
        document_index=MagicMock(),
        user_selected_filters=None,
        project_id_filter=None,
        enable_slack_search=False,
    )


def _run(
    tool: SearchTool,
    *,
    detected_source_filter: list[DocumentSource] | None,
    connected_sources: list[DocumentSource],
) -> MagicMock:
    """Run tool.run() with all DB/LLM deps mocked. Returns the search_pipeline mock.

    search_pipeline returns no chunks, so run() takes the empty-results early
    return and the enrichment phase never executes.
    """
    mock_search_pipeline = MagicMock(return_value=[])
    with (
        patch(f"{MODULE}.get_session_with_current_tenant") as mock_session_ctx,
        patch(f"{MODULE}.build_access_filters_for_user", return_value=[]),
        patch(f"{MODULE}.get_current_search_settings", return_value=MagicMock()),
        patch(f"{MODULE}.EmbeddingModel"),
        patch(f"{MODULE}.get_federated_retrieval_functions", return_value=[]),
        patch(
            f"{MODULE}.fetch_unique_document_sources", return_value=connected_sources
        ),
        patch(f"{MODULE}.semantic_query_rephrase", return_value="rephrased query"),
        patch(f"{MODULE}.keyword_query_expansion", return_value=[]),
        patch(f"{MODULE}.extract_source_filter", return_value=detected_source_filter),
        patch(f"{MODULE}.weighted_reciprocal_rank_fusion", return_value=[]),
        patch(f"{MODULE}.merge_individual_chunks", return_value=[]),
        patch(f"{MODULE}.search_pipeline", mock_search_pipeline),
    ):
        mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        override_kwargs = SearchToolOverrideKwargs(
            starting_citation_num=1,
            original_query="find the runbook in confluence",
            message_history=[
                ChatMinimalTextMessage(
                    message="find the runbook in confluence",
                    message_type=MessageType.USER,
                )
            ],
            skip_query_expansion=False,
        )
        tool.run(
            placement=Placement(turn_index=0, tab_index=0),
            override_kwargs=override_kwargs,
            queries=["runbook"],
        )
    return mock_search_pipeline


def _filters_passed_to_search(mock_search_pipeline: MagicMock) -> list[Any]:
    return [
        call.kwargs["chunk_search_request"].user_selected_filters
        for call in mock_search_pipeline.call_args_list
    ]


def test_detected_source_filter_is_passed_to_search() -> None:
    """When extract_source_filter returns sources, every search runs scoped to them."""
    tool = _make_tool()
    mock_search_pipeline = _run(
        tool,
        detected_source_filter=[DocumentSource.CONFLUENCE],
        connected_sources=[
            DocumentSource.SLACK,
            DocumentSource.CONFLUENCE,
            DocumentSource.GITHUB,
        ],
    )

    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is not None
        assert applied.source_type == [DocumentSource.CONFLUENCE]


def test_no_detected_source_filter_leaves_search_unscoped() -> None:
    """When extract_source_filter returns None, no source filter is applied."""
    tool = _make_tool()
    mock_search_pipeline = _run(
        tool,
        detected_source_filter=None,
        connected_sources=[DocumentSource.SLACK, DocumentSource.CONFLUENCE],
    )

    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is None or applied.source_type is None
