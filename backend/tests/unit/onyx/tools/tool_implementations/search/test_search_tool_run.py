from __future__ import annotations

from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import SearchToolFilterDelta
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import SearchTool

MODULE = "onyx.tools.tool_implementations.search.search_tool"

# What decide_search_scope returns: the scope to apply now (or None for everything).
ScopeDecision = list[DocumentSource] | None


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
    connected_sources: list[DocumentSource],
    decision: ScopeDecision = None,
    decide_mock: MagicMock | None = None,
    skip_query_expansion: bool = False,
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
        patch(f"{MODULE}.weighted_reciprocal_rank_fusion", return_value=[]),
        patch(f"{MODULE}.merge_individual_chunks", return_value=[]),
        patch(f"{MODULE}.search_pipeline", mock_search_pipeline),
    ):
        mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)
        tool.run(
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
            queries=["ticket"],
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


def _emitted_filter_sources(tool: SearchTool) -> list[list[str]]:
    """Sources of each SearchToolFilterDelta the tool emitted to the UI."""
    emit_mock = cast(MagicMock, tool.emitter.emit)
    emitted = [call.args[0].obj for call in emit_mock.call_args_list]
    return [obj.sources for obj in emitted if isinstance(obj, SearchToolFilterDelta)]


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
    """A scope narrower than the connected sources surfaces a filter to the UI."""
    tool = _make_tool()
    _run(
        tool,
        decision=[DocumentSource.CONFLUENCE],
        connected_sources=[DocumentSource.CONFLUENCE, DocumentSource.GITHUB],
    )
    assert _emitted_filter_sources(tool) == [["confluence"]]


def test_no_filter_delta_when_scope_covers_all_sources() -> None:
    """Scoping to every connected source is equivalent to an unscoped search, so
    no filter is surfaced (the UI keeps its default 'internal documents' label)."""
    tool = _make_tool()
    connected = [DocumentSource.CONFLUENCE, DocumentSource.GITHUB]
    _run(tool, decision=connected, connected_sources=connected)
    assert _emitted_filter_sources(tool) == []


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
