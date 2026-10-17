from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import (
    BaseFilters,
    InferenceChunk,
    InferenceSection,
    UserAccessFilters,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import SearchToolFilterDelta
from onyx.tools.models import ChatMinimalTextMessage, SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import SearchTool

MODULE = "onyx.tools.tool_implementations.search.search_tool"

# What decide_search_scope returns: the scope to apply now (or None for everything).
ScopeDecision = list[DocumentSource] | None


def _make_tool(
    user_selected_filters: BaseFilters | None = None,
    auto_detect_filters: bool = True,
    selection_llm_factory: MagicMock | None = None,
    primary_llm_cost_checked: bool = True,
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
        auto_detect_filters=auto_detect_filters,
        selection_llm_factory=selection_llm_factory,
        primary_llm_cost_checked=primary_llm_cost_checked,
    )


def _run(
    tool: SearchTool,
    *,
    connected_sources: list[DocumentSource],
    decision: ScopeDecision = None,
    decide_mock: MagicMock | None = None,
    skip_query_expansion: bool = False,
    sections: list[InferenceSection] | None = None,
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
        patch(
            f"{MODULE}.build_access_filters_for_user",
            return_value=UserAccessFilters(access_control_list=[], cc_pair_access=None),
        ),
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
        patch(f"{MODULE}.merge_individual_chunks", return_value=sections or []),
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


def test_empty_search_never_resolves_selection_model() -> None:
    resolver = MagicMock(side_effect=ValueError("selection model unavailable"))
    tool = _make_tool(selection_llm_factory=resolver)

    _run(tool, connected_sources=[DocumentSource.GITHUB])

    resolver.assert_not_called()


def test_slack_search_over_primary_budget_skips_only_slack_lane() -> None:
    tool = _make_tool(auto_detect_filters=False, primary_llm_cost_checked=False)
    tool.enable_slack_search = True
    tool.llm.config.api_key = "primary-key"
    error = OnyxError(OnyxErrorCode.RATE_LIMITED, "Provider budget exceeded")
    with (
        patch.object(
            tool, "_prefetch_slack_data", return_value=("slack-token", None, {})
        ),
        patch(f"{MODULE}.check_llm_cost_limit_for_provider", side_effect=error) as cost,
        patch.object(tool, "_run_slack_search") as slack,
    ):
        _run(tool, connected_sources=[DocumentSource.SLACK], skip_query_expansion=True)

    assert cost.call_args.kwargs["llm_provider_api_key"] == "primary-key"
    slack.assert_not_called()


def test_search_uses_selection_model_only_for_evidence_decisions() -> None:
    selection_llm = MagicMock()
    resolver = MagicMock(return_value=selection_llm)
    tool = _make_tool(selection_llm_factory=resolver)
    chunk = InferenceChunk(
        document_id="doc-1",
        chunk_id=0,
        content="selected evidence",
        source_type=DocumentSource.GITHUB,
        semantic_identifier="Runbook",
        title="Runbook",
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb="selected evidence",
    )
    section = InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content=chunk.content
    )
    sections = [section]
    with (
        patch(f"{MODULE}.populate_file_ids_on_sections"),
        patch(f"{MODULE}.convert_inference_sections_to_search_docs", return_value=[]),
        patch(f"{MODULE}.get_llm_token_counter", return_value=lambda _: 0),
        patch(f"{MODULE}._trim_sections_by_tokens", return_value=sections),
        patch(
            f"{MODULE}.select_sections_for_expansion",
            return_value=(sections, None),
        ) as select,
        patch(f"{MODULE}.expand_section_with_context", return_value=section) as expand,
        patch(f"{MODULE}.merge_overlapping_sections", return_value=sections),
        patch(
            f"{MODULE}.convert_inference_sections_to_llm_string",
            return_value=("selected evidence", {1: "doc-1"}),
        ),
    ):
        _run(tool, connected_sources=[DocumentSource.GITHUB], sections=sections)

    resolver.assert_called_once_with()
    assert select.call_args.kwargs["llm"] is selection_llm
    assert expand.call_args.kwargs["llm"] is selection_llm
    assert select.call_args.kwargs["enforce_llm_input_budget"] is True
    assert expand.call_args.kwargs["enforce_llm_input_budget"] is True


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


def test_auto_detect_disabled_skips_scope_decision() -> None:
    """With auto-detect off, no scope decision runs and the search stays unscoped."""
    tool = _make_tool(auto_detect_filters=False)
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]
    decide_mock = MagicMock(return_value=[DocumentSource.ZENDESK])

    mock_search_pipeline = _run(
        tool, decide_mock=decide_mock, connected_sources=connected
    )

    decide_mock.assert_not_called()
    assert _emitted_filter_sources(tool) == []
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


def test_custom_agent_project_search_keeps_source_scope_and_both_file_filters() -> None:
    tool: SearchTool = _make_tool(
        BaseFilters(source_type=[DocumentSource.GITHUB]), auto_detect_filters=False
    )
    tool.project_id_filter = 42
    tool.persona_id_filter = 7

    search: MagicMock = _run(
        tool, connected_sources=[DocumentSource.GITHUB, DocumentSource.GOOGLE_DRIVE]
    )

    assert search.call_count > 0
    for call in search.call_args_list:
        assert call.kwargs["project_id_filter"] == 42
        assert call.kwargs["persona_id_filter"] == 7
        assert call.kwargs[
            "chunk_search_request"
        ].user_selected_filters.source_type == [DocumentSource.GITHUB]


@pytest.mark.parametrize("project_id", [None, 99])
@pytest.mark.parametrize(
    "selected_sources, expected_sources",
    [
        (None, [DocumentSource.GITHUB, DocumentSource.USER_FILE]),
        ([DocumentSource.GITHUB], [DocumentSource.GITHUB]),
        (
            [DocumentSource.GITHUB, DocumentSource.USER_FILE],
            [DocumentSource.GITHUB, DocumentSource.USER_FILE],
        ),
    ],
)
def test_inferred_scope_retains_context_files_within_explicit_selection(
    project_id: int | None,
    selected_sources: list[DocumentSource] | None,
    expected_sources: list[DocumentSource],
) -> None:
    tool: SearchTool = _make_tool(BaseFilters(source_type=selected_sources))
    tool.project_id_filter = project_id
    tool.persona_id_filter = 42
    decision: list[DocumentSource] = [DocumentSource.GITHUB]
    search: MagicMock = _run(
        tool,
        decision=decision,
        connected_sources=[
            DocumentSource.GITHUB,
            DocumentSource.USER_FILE,
            DocumentSource.SLACK,
        ],
    )
    assert search.call_args_list
    for call in search.call_args_list:
        assert call.kwargs["project_id_filter"] == project_id
        assert call.kwargs["persona_id_filter"] == 42
        assert (
            call.kwargs["chunk_search_request"].user_selected_filters.source_type
            == expected_sources
        )
    expected_values: list[str] = [source.value for source in expected_sources]
    assert _emitted_filter_sources(tool) == [expected_values]
    assert tool._search_cycles[-1].searched_sources == expected_values
    assert decision == [DocumentSource.GITHUB]
    assert tool.user_selected_filters is not None
    assert tool.user_selected_filters.source_type == selected_sources
