from typing import Any
from unittest.mock import MagicMock, patch

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import BaseFilters
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import UserMessage
from onyx.tools.interface import ToolContext
from onyx.tools.progress import SearchFilters
from onyx.tools.tool_implementations.search.search_tool import SearchTool

MODULE = "onyx.tools.tool_implementations.search.search_tool"

# What decide_search_scope returns: the scope to apply now (or None for everything).
ScopeDecision = list[DocumentSource] | None


def _make_tool(
    user_selected_filters: BaseFilters | None = None,
    auto_detect_filters: bool = True,
) -> SearchTool:
    """Instantiate SearchTool with non-DB deps mocked; DB/LLM calls are patched in _run."""
    return SearchTool(
        tool_id=1,
        user=MagicMock(is_anonymous=False),
        persona_search_info=MagicMock(document_set_names=[]),
        llm=MagicMock(),
        document_index=MagicMock(),
        user_selected_filters=user_selected_filters,
        project_id_filter=None,
        enable_slack_search=False,
        auto_detect_filters=auto_detect_filters,
    )


def _run(
    tool: SearchTool,
    *,
    connected_sources: list[DocumentSource],
    decision: ScopeDecision = None,
    decide_mock: MagicMock | None = None,
    skip_query_expansion: bool = False,
    progress: list[ToolProgress] | None = None,
) -> MagicMock:
    """Run tool.run() with all DB/LLM deps mocked; returns the search_pipeline mock.

    decide_search_scope is replaced by `decide_mock` when given (so its call args
    can be inspected), otherwise by a stub returning `decision`. search_pipeline
    returns no chunks, so run() takes the empty-results early return.
    """
    mock_search_pipeline = MagicMock(return_value=[])
    decide = (
        decide_mock if decide_mock is not None else MagicMock(return_value=decision)
    )
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
        patch(f"{MODULE}.decide_search_scope", decide),
        patch(f"{MODULE}.decide_time_filter", MagicMock(return_value=None)),
        patch(f"{MODULE}.weighted_reciprocal_rank_fusion", return_value=[]),
        patch(f"{MODULE}.merge_individual_chunks", return_value=[]),
        patch(f"{MODULE}.search_pipeline", mock_search_pipeline),
    ):
        mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)
        tool.run(
            invocation=ToolInvocation(
                call_id="search",
                arguments={"queries": ["ticket"]},
                cancellation=CancellationSignal(),
                update=progress.append
                if progress is not None
                else lambda _progress: None,
                messages=[UserMessage(content="resolve the ticket")],
            ),
            context=ToolContext(skip_search_query_expansion=skip_query_expansion),
        )
    return mock_search_pipeline


def _filters_passed_to_search(mock_search_pipeline: MagicMock) -> list[Any]:
    return [
        call.kwargs["chunk_search_request"].user_selected_filters
        for call in mock_search_pipeline.call_args_list
    ]


def _queries_sent(mock_search_pipeline: MagicMock) -> list[str]:
    return [
        call.kwargs["chunk_search_request"].query
        for call in mock_search_pipeline.call_args_list
    ]


def _emitted_filter_sources(progress: list[ToolProgress]) -> list[list[str]]:
    return [
        item.details.sources
        for item in progress
        if isinstance(item.details, SearchFilters)
    ]


def test_decided_scope_is_passed_to_search() -> None:
    """When the filter flow decides a source, every search runs scoped to it."""
    tool = _make_tool()
    mock_search_pipeline = _run(
        tool,
        decision=[DocumentSource.CONFLUENCE],
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


def test_filter_delta_emitted_for_a_subset_scope() -> None:
    updates: list[ToolProgress] = []
    """A scope narrower than the connected sources surfaces a filter to the UI."""
    tool = _make_tool()
    _run(
        tool,
        progress=updates,
        decision=[DocumentSource.CONFLUENCE],
        connected_sources=[DocumentSource.CONFLUENCE, DocumentSource.GITHUB],
    )
    assert _emitted_filter_sources(updates) == [["confluence"]]


def test_no_filter_delta_when_scope_covers_all_sources() -> None:
    updates: list[ToolProgress] = []
    """Scoping to every connected source is equivalent to an unscoped search, so
    no filter is surfaced (the UI keeps its default 'internal documents' label)."""
    tool = _make_tool()
    connected = [DocumentSource.CONFLUENCE, DocumentSource.GITHUB]
    _run(tool, progress=updates, decision=connected, connected_sources=connected)
    assert _emitted_filter_sources(updates) == []


def test_no_decided_scope_leaves_search_unscoped() -> None:
    """A no-scope decision applies no source filter."""
    tool = _make_tool()
    mock_search_pipeline = _run(
        tool,
        decision=None,
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
        decision=[DocumentSource.CONFLUENCE],
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
        decision=None,
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


def test_cached_expansion_is_reused_on_a_new_filter_not_a_repeat() -> None:
    """The first call expands (and caches). A repeat call on a NOT-yet-searched
    source reuses the cached expansion; a repeat on an already-searched source
    does not (the agent is expected to vary terms there)."""
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.ASANA]

    # Call 1: first search (expansion runs) scoped to Zendesk -> caches expansion.
    _run(tool, decision=[DocumentSource.ZENDESK], connected_sources=connected)

    # Call 2: repeat call, walk advanced to Asana (new) -> reuse cached expansion.
    new_filter = _run(
        tool,
        decision=[DocumentSource.ASANA],
        connected_sources=connected,
        skip_query_expansion=True,
    )
    assert "rephrased query" in _queries_sent(new_filter), (
        "cached expansion should be reused when searching a new source"
    )

    # Call 3: repeat call on Asana again (already searched) -> no reuse.
    repeat = _run(
        tool,
        decision=[DocumentSource.ASANA],
        connected_sources=connected,
        skip_query_expansion=True,
    )
    assert "rephrased query" not in _queries_sent(repeat), (
        "a same-source repeat should not re-apply the cached expansion"
    )


def test_no_scope_decision_is_not_repeated_within_a_turn() -> None:
    """Once a cycle's scope decision comes back unscoped, the conversation has no
    source directive (which can't change this turn), so later cycles skip the
    decision instead of burning another LLM call."""
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]
    decide_mock = MagicMock(return_value=None)

    _run(tool, decide_mock=decide_mock, connected_sources=connected)
    _run(tool, decide_mock=decide_mock, connected_sources=connected)

    assert decide_mock.call_count == 1, (
        "decide_search_scope should run once, then latch off after a no-scope result"
    )


def test_scope_decision_keeps_running_while_a_directive_is_present() -> None:
    """A routed decision does not latch the skip — the walk must keep deciding on
    later cycles (e.g. to advance a backoff sequence to the next source)."""
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]
    decide_mock = MagicMock(
        side_effect=[[DocumentSource.ZENDESK], [DocumentSource.CONFLUENCE]]
    )

    _run(tool, decide_mock=decide_mock, connected_sources=connected)
    _run(tool, decide_mock=decide_mock, connected_sources=connected)

    assert decide_mock.call_count == 2


def test_prior_cycles_accumulate_across_calls_for_the_walk() -> None:
    """A backoff sequence advances: the first call's queries + resolved scope are
    passed back to decide_search_scope as previous_cycles on the second."""
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]

    # Mimic the walk: first call routes to Zendesk, second to Confluence.
    decide_mock = MagicMock(
        side_effect=[[DocumentSource.ZENDESK], [DocumentSource.CONFLUENCE]]
    )
    _run(tool, decide_mock=decide_mock, connected_sources=connected)
    _run(tool, decide_mock=decide_mock, connected_sources=connected)

    # previous_cycles is the 4th positional arg.
    first_cycles = decide_mock.call_args_list[0].args[3]
    second_cycles = decide_mock.call_args_list[1].args[3]
    assert first_cycles == []
    assert len(second_cycles) == 1
    assert second_cycles[0].searched_sources == ["zendesk"]
    assert second_cycles[0].queries == ["ticket"]
    assert second_cycles[0].cycle_number == 1


def test_auto_detect_disabled_skips_scope_decision() -> None:
    updates: list[ToolProgress] = []
    """With auto-detect off, no scope decision runs and the search stays unscoped."""
    tool = _make_tool(auto_detect_filters=False)
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]
    decide_mock = MagicMock(return_value=[DocumentSource.ZENDESK])

    mock_search_pipeline = _run(
        tool, progress=updates, decide_mock=decide_mock, connected_sources=connected
    )

    decide_mock.assert_not_called()
    assert _emitted_filter_sources(updates) == []
    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is None or applied.source_type is None


def test_auto_detect_disabled_keeps_user_selected_filters() -> None:
    """With auto-detect off, user/persona-selected filters are still applied."""
    restriction = [DocumentSource.CONFLUENCE, DocumentSource.GITHUB]
    tool = _make_tool(BaseFilters(source_type=restriction), auto_detect_filters=False)
    decide_mock = MagicMock(return_value=[DocumentSource.CONFLUENCE])

    mock_search_pipeline = _run(
        tool,
        decide_mock=decide_mock,
        connected_sources=[
            DocumentSource.CONFLUENCE,
            DocumentSource.GITHUB,
            DocumentSource.SLACK,
        ],
    )

    decide_mock.assert_not_called()
    filters = _filters_passed_to_search(mock_search_pipeline)
    assert filters, "search_pipeline was never called"
    for applied in filters:
        assert applied is not None
        assert applied.source_type == restriction
