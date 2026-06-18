from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import SearchTool

MODULE = "onyx.tools.tool_implementations.search.search_tool"

# What decide_search_scope returns: (scope to apply now, next source).
ScopeDecision = tuple[list[DocumentSource] | None, DocumentSource | None]


def _make_tool(user_selected_filters: BaseFilters | None = None) -> SearchTool:
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
    )


def _run(
    tool: SearchTool,
    *,
    decision: ScopeDecision,
    connected_sources: list[DocumentSource],
) -> MagicMock:
    """Run tool.run() with all DB/LLM deps mocked. Returns the search_pipeline mock.

    `decision` is what the filter flow returns; the tool resolves it to a scope.
    search_pipeline returns no chunks, so run() takes the empty-results early
    return.
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
        patch(f"{MODULE}.decide_search_scope", return_value=decision),
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


def test_decided_scope_is_passed_to_search() -> None:
    """When the filter flow decides a source, every search runs scoped to it."""
    tool = _make_tool()
    mock_search_pipeline = _run(
        tool,
        decision=([DocumentSource.CONFLUENCE], None),
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


def test_no_decided_scope_leaves_search_unscoped() -> None:
    """A no-scope decision applies no source filter."""
    tool = _make_tool()
    mock_search_pipeline = _run(
        tool,
        decision=(None, None),
        connected_sources=[DocumentSource.SLACK, DocumentSource.CONFLUENCE],
    )

    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is None or applied.source_type is None


def test_persona_restriction_is_refined_by_the_decision() -> None:
    """A persona source restriction is the outer bound; the decision refines
    WITHIN it (here, down to a single source)."""
    tool = _make_tool(
        BaseFilters(
            source_type=[
                DocumentSource.CONFLUENCE,
                DocumentSource.GITHUB,
                DocumentSource.SLACK,
            ]
        )
    )
    mock_search_pipeline = _run(
        tool,
        decision=([DocumentSource.CONFLUENCE], None),
        connected_sources=[
            DocumentSource.CONFLUENCE,
            DocumentSource.GITHUB,
            DocumentSource.SLACK,
        ],
    )

    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is not None
        assert applied.source_type == [DocumentSource.CONFLUENCE]


def test_persona_restriction_applies_when_decision_does_not_route() -> None:
    """With a persona restriction and a no-scope decision, the search stays scoped
    to the restriction (never broadens to everything)."""
    restriction = [DocumentSource.CONFLUENCE, DocumentSource.GITHUB]
    tool = _make_tool(BaseFilters(source_type=restriction))
    mock_search_pipeline = _run(
        tool,
        decision=(None, None),
        connected_sources=[
            DocumentSource.CONFLUENCE,
            DocumentSource.GITHUB,
            DocumentSource.SLACK,
        ],
    )

    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is not None
        assert applied.source_type == restriction
