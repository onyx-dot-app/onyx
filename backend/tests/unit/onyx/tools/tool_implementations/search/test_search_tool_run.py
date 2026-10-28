from threading import Barrier
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.agents.runtime import Agent
from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import (
    BaseFilters,
    DocumentTimeField,
    InferenceChunk,
    InferenceSection,
    SearchCycle,
    SearchDocsResponse,
    TimeFilter,
    UserAccessFilters,
)
from onyx.document_index.interfaces import DocumentIndex
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.search.models import (
    SearchContext,
    SearchPlanningResult,
)
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
    update_search_context,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient

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
    progress: list[ToolProgress] | None = None,
    sections: list[InferenceSection] | None = None,
    context: ToolContext | None = None,
) -> MagicMock:
    """Mock retrieval and scope selection; supplied sections exercise context expansion."""
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
        result = tool.run(
            invocation=ToolInvocation(
                call_id="search",
                arguments={"queries": ["ticket"]},
                cancellation=CancellationSignal(),
                update=lambda item: (
                    progress.append(item.model_copy(deep=True))
                    if progress is not None
                    else None
                ),
                messages=[UserMessage(content="resolve the ticket")],
            ),
            context=(context or ToolContext()).model_copy(
                update={"skip_search_query_expansion": skip_query_expansion}
            ),
        )
    assert isinstance(result, ToolResult)
    if context is not None:
        context.search_context = update_search_context(
            context.search_context,
            [
                ToolResultMessage(
                    tool_call_id="search",
                    tool_name="internal_search",
                    content=result.content,
                    metadata=result.metadata,
                    is_error=result.is_error,
                )
            ],
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


@pytest.mark.parametrize("selection_mode", ["configured", "primary", "unavailable"])
@pytest.mark.parametrize("with_slack", [False, True])
def test_search_uses_one_selection_model_per_invocation(
    selection_mode: str,
    with_slack: bool,
) -> None:
    resolver = MagicMock()
    tool = _make_tool(selection_llm_factory=resolver, primary_llm_cost_checked=False)
    tool.enable_slack_search = with_slack
    selection_llm = MagicMock() if selection_mode == "configured" else tool.llm
    resolver.return_value = selection_llm
    if selection_mode == "unavailable":
        resolver.side_effect = ValueError("selection unavailable")
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
        patch(f"{MODULE}.check_llm_cost_limit_for_provider") as cost,
        patch.object(
            tool, "_prefetch_slack_data", return_value=("slack-token", None, {})
        ),
        patch.object(tool, "_run_slack_search", return_value=[]),
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
        _run(tool, connected_sources=[DocumentSource.GITHUB], sections=sections)

    assert resolver.call_count == 2
    assert select.call_args.kwargs["llm"] is selection_llm
    assert expand.call_args.kwargs["llm"] is selection_llm
    assert select.call_args.kwargs["enforce_llm_input_budget"] is (
        selection_mode == "configured"
    )
    assert expand.call_args.kwargs["enforce_llm_input_budget"] is (
        selection_mode == "configured"
    )
    assert cost.call_count == (2 if with_slack or selection_mode != "configured" else 0)


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
        if isinstance(item.details, SearchDocsResponse) and item.details.sources
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
    """A scope narrower than the connected sources surfaces a filter to the UI."""
    updates: list[ToolProgress] = []
    tool = _make_tool()
    _run(
        tool,
        progress=updates,
        decision=[DocumentSource.CONFLUENCE],
        connected_sources=[DocumentSource.CONFLUENCE, DocumentSource.GITHUB],
    )
    assert _emitted_filter_sources(updates) == [["confluence"], ["confluence"]]


def test_no_filter_delta_when_scope_covers_all_sources() -> None:
    """Scoping to every connected source is equivalent to an unscoped search, so
    no filter is surfaced (the UI keeps its default 'internal documents' label)."""
    updates: list[ToolProgress] = []
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
    context = ToolContext()
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.ASANA]

    # Call 1: first search (expansion runs) scoped to Zendesk -> caches expansion.
    _run(
        tool,
        context=context,
        decision=[DocumentSource.ZENDESK],
        connected_sources=connected,
    )

    # Call 2: repeat call, walk advanced to Asana (new) -> reuse cached expansion.
    new_filter = _run(
        tool,
        context=context,
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
        context=context,
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
    context = ToolContext()
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]
    decide_mock = MagicMock(return_value=None)

    _run(tool, context=context, decide_mock=decide_mock, connected_sources=connected)
    _run(tool, context=context, decide_mock=decide_mock, connected_sources=connected)

    assert decide_mock.call_count == 1, (
        "decide_search_scope should run once, then latch off after a no-scope result"
    )


def test_scope_decision_keeps_running_while_a_directive_is_present() -> None:
    """A routed decision does not latch the skip — the walk must keep deciding on
    later cycles (e.g. to advance a backoff sequence to the next source)."""
    context = ToolContext()
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]
    decide_mock = MagicMock(
        side_effect=[[DocumentSource.ZENDESK], [DocumentSource.CONFLUENCE]]
    )

    _run(tool, context=context, decide_mock=decide_mock, connected_sources=connected)
    _run(tool, context=context, decide_mock=decide_mock, connected_sources=connected)

    assert decide_mock.call_count == 2


def test_prior_cycles_accumulate_across_calls_for_the_walk() -> None:
    """A backoff sequence advances: the first call's queries + resolved scope are
    passed back to decide_search_scope as previous_cycles on the second."""
    context = ToolContext()
    tool = _make_tool()
    connected = [DocumentSource.ZENDESK, DocumentSource.CONFLUENCE]

    # Mimic the walk: first call routes to Zendesk, second to Confluence.
    decide_mock = MagicMock(
        side_effect=[[DocumentSource.ZENDESK], [DocumentSource.CONFLUENCE]]
    )
    _run(tool, context=context, decide_mock=decide_mock, connected_sources=connected)
    _run(tool, context=context, decide_mock=decide_mock, connected_sources=connected)

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
    updates: list[ToolProgress] = []
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
    context = ToolContext()
    tool: SearchTool = _make_tool(BaseFilters(source_type=selected_sources))
    tool.project_id_filter = project_id
    tool.persona_id_filter = 42
    decision: list[DocumentSource] = [DocumentSource.GITHUB]
    updates: list[ToolProgress] = []
    search: MagicMock = _run(
        tool,
        context=context,
        decision=decision,
        progress=updates,
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
    assert _emitted_filter_sources(updates) == [expected_values, expected_values]
    assert context.search_context.search_cycles[-1].searched_sources == expected_values
    assert decision == [DocumentSource.GITHUB]
    assert tool.user_selected_filters is not None
    assert tool.user_selected_filters.source_type == selected_sources


def test_shared_search_tool_keeps_conversations_separate() -> None:
    tool = _make_tool()
    first = ToolContext()
    second = ToolContext()
    sources = [DocumentSource.SLACK, DocumentSource.GITHUB]
    first_scope = MagicMock(return_value=[DocumentSource.SLACK])
    second_scope = MagicMock(return_value=[DocumentSource.GITHUB])

    _run(tool, context=first, connected_sources=sources, decide_mock=first_scope)
    _run(tool, context=second, connected_sources=sources, decide_mock=second_scope)
    _run(tool, context=first, connected_sources=sources, decide_mock=first_scope)

    assert second_scope.call_args.args[3] == []
    assert len(first_scope.call_args.args[3]) == 1
    assert first.search_context.search_cycles[0].searched_sources == ["slack"]
    assert second.search_context.search_cycles[0].searched_sources == ["github"]


def test_selected_documents_are_published_before_context_expansion() -> None:
    chunk = InferenceChunk(
        document_id="ticket",
        source_type=DocumentSource.CONFLUENCE,
        semantic_identifier="Support ticket",
        title="Support ticket",
        chunk_id=0,
        blurb="Evidence",
        content="Evidence",
        source_links={0: "https://example.com/ticket"},
        image_file_id=None,
        section_continuation=False,
        boost=0,
        score=1,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
    )
    section = InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content="Evidence"
    )
    updates: list[ToolProgress] = []

    def expand(
        section: InferenceSection,
        user_query: str,  # noqa: ARG001
        llm: LLM,  # noqa: ARG001
        document_index: DocumentIndex,  # noqa: ARG001
        expand_override: bool,  # noqa: ARG001
        enforce_llm_input_budget: bool = False,  # noqa: ARG001
    ) -> InferenceSection:
        details = updates[-1].details
        assert isinstance(details, SearchDocsResponse)
        assert details.displayed_docs is not None
        assert [doc.document_id for doc in details.displayed_docs] == ["ticket"]
        assert "ticket" in details.queries
        assert details.sources == ["confluence"]
        return section

    with (
        patch(f"{MODULE}.populate_file_ids_on_sections"),
        patch(f"{MODULE}.get_llm_token_counter"),
        patch(f"{MODULE}._trim_sections_by_tokens", return_value=[section]),
        patch(
            f"{MODULE}.select_sections_for_expansion",
            return_value=([section], ["ticket"]),
        ),
        patch(f"{MODULE}.expand_section_with_context", side_effect=expand) as expansion,
        patch(
            f"{MODULE}.convert_inference_sections_to_llm_string",
            return_value=("Evidence", {1: "ticket"}),
        ),
    ):
        _run(
            _make_tool(),
            connected_sources=[DocumentSource.CONFLUENCE, DocumentSource.SLACK],
            decision=[DocumentSource.CONFLUENCE],
            progress=updates,
            sections=[section],
        )
    expansion.assert_called_once()
    first = updates[0].details
    assert isinstance(first, SearchDocsResponse)
    assert first.displayed_docs is None
    assert first.search_docs == []


@pytest.mark.parametrize("merge_calls", [False, True])
def test_sdk_searches_preserve_context_and_call_identity(merge_calls: bool) -> None:
    tool = _make_tool()
    context = ToolContext(
        skip_search_query_expansion=True,
        search_context=SearchContext(
            search_cycles=(
                SearchCycle(
                    cycle_number=1,
                    queries=["prior"],
                    searched_sources=["slack"],
                ),
            )
        ),
    )
    before = context.model_dump_json()
    execution_count = 1 if merge_calls else 2
    retrievals_started = Barrier(2)

    def retrieve(query: str, *_args: object) -> list[InferenceChunk]:
        # The shared original question must not satisfy the two-call barrier.
        if query in {"first", "second"}:
            retrievals_started.wait(timeout=5)
        return []

    replies = iter(
        [
            AssistantMessage(
                content=[
                    ToolCall(
                        id=query, name=SearchTool.NAME, arguments={"queries": [query]}
                    )
                    for query in ("first", "second")
                ]
            ),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )
    agent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[tool.bind(lambda: context)],
        # Per-call approval checks prevent merging, even when they permit execution.
        before_tool_call=None if merge_calls else lambda _: None,
    )

    with (
        patch(f"{MODULE}.get_session_with_current_tenant"),
        patch(
            f"{MODULE}.build_access_filters_for_user",
            return_value=UserAccessFilters(
                access_control_list=[],
                cc_pair_access=None,
            ),
        ),
        patch(f"{MODULE}.get_current_search_settings", return_value=MagicMock()),
        patch(f"{MODULE}.EmbeddingModel"),
        patch(f"{MODULE}.get_federated_retrieval_functions", return_value=[]),
        patch(
            f"{MODULE}.fetch_unique_document_sources",
            return_value=[DocumentSource.GITHUB],
        ),
        patch(
            f"{MODULE}.decide_search_scope", return_value=[DocumentSource.GITHUB]
        ) as scope,
        patch(f"{MODULE}.decide_time_filter", return_value=None) as time_filter,
        patch.object(tool, "_run_search_for_query", side_effect=retrieve),
    ):
        run = agent.start(max_steps=2, messages=[UserMessage(content="Find evidence")])
        try:
            assert run.result(10).output.text == "done"
            assert run.wait_for_idle(5)
            results = [
                message
                for message in run.snapshot().messages
                if isinstance(message, ToolResultMessage)
            ]
        finally:
            retrievals_started.abort()
            run.cancel()
            assert run.wait_for_idle(5)

    assert [result.tool_call_id for result in results] == ["first", "second"]
    assert context.model_dump_json() == before
    assert scope.call_count == time_filter.call_count == execution_count
    for call in scope.call_args_list:
        assert call.args[3] == list(context.search_context.search_cycles)
    for result in results:
        assert not result.is_error
        assert isinstance(result.metadata, SearchPlanningResult)
        assert result.metadata.original_queries == (
            ("first", "second") if merge_calls else (result.tool_call_id,)
        )
        assert result.metadata.tool_call_id == (
            "first" if merge_calls else result.tool_call_id
        )
        assert result.metadata.searched_sources == ("github",)
        assert isinstance(result.details, SearchDocsResponse)
        assert result.details.sources == []
    updated = update_search_context(context.search_context, results)
    assert len(updated.search_cycles) == 1 + execution_count
    assert [cycle.queries for cycle in updated.search_cycles[1:]] == (
        [["first", "second"]] if merge_calls else [["first"], ["second"]]
    )


def test_search_context_folds_merged_results_once_in_model_order() -> None:
    initial = SearchContext()
    first = SearchPlanningResult(
        tool_call_id="merged",
        original_queries=("one", "two"),
        searched_sources=("github",),
        cached_expansion=("first", ("one",)),
        time_filter_computed=True,
    )
    later = SearchPlanningResult(
        tool_call_id="later",
        original_queries=("three",),
        searched_sources=("slack",),
        cached_expansion=("last", ("three",)),
        scope_decision_settled=True,
        time_filter=TimeFilter(field=DocumentTimeField.UPDATED_AT),
        time_filter_computed=True,
    )
    results = [
        ToolResultMessage(
            tool_call_id=call_id,
            tool_name="internal_search",
            content="",
            metadata=planning,
            is_error=error,
        )
        for call_id, planning, error in (
            ("one", first, False),
            ("two", first.model_copy(), False),
            ("failure", later, True),
            ("three", later, False),
        )
    ]
    final = update_search_context(initial, results)
    assert initial == SearchContext()
    assert [cycle.queries for cycle in final.search_cycles] == [
        ["one", "two"],
        ["three"],
    ]
    assert [cycle.cycle_number for cycle in final.search_cycles] == [1, 2]
    assert final.cached_expansion == ("last", ("three",))
    assert final.scope_decision_settled
    assert final.time_filter_computed and final.time_filter is None


def test_empty_source_selection_and_failed_retrieval_do_not_advance_context() -> None:
    context = ToolContext()
    empty_tool = _make_tool(BaseFilters(source_type=[]))
    pipeline = _run(
        empty_tool, context=context, connected_sources=[DocumentSource.GITHUB]
    )
    pipeline.assert_not_called()
    assert context.search_context == SearchContext()

    tool = _make_tool()
    with patch.object(
        tool, "_run_search_for_query", side_effect=RuntimeError("retrieval failed")
    ):
        _run(tool, context=context, connected_sources=[DocumentSource.GITHUB])
    assert context.search_context == SearchContext()
