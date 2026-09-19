"""SearchTool side of search receipts: lane capture and receipt-scope gating."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import (
    BaseFilters,
    PersonaSearchInfo,
    SearchDocsResponse,
    SearchReceiptScope,
)
from onyx.federated_connectors.federated_retrieval import FederatedRetrievalInfo
from onyx.secondary_llm_flows.time_filter import DocumentTimeField, TimeFilter
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import (
    ChatMinimalTextMessage,
    SearchToolOverrideKwargs,
    ToolCallKickoff,
    ToolResponse,
)
from onyx.tools.tool_implementations.search.constants import (
    KEYWORD_QUERY_HYBRID_ALPHA,
)
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
    _build_retrieval_candidate_lanes,
    _distinct_section_document_ids,
)
from onyx.tools.tool_runner import run_tool_calls


def _chunk(document_id: str, chunk_id: int) -> MagicMock:
    chunk = MagicMock()
    chunk.document_id = document_id
    chunk.chunk_id = chunk_id
    return chunk


def _section(document_id: str) -> MagicMock:
    section = MagicMock()
    section.center_chunk = _chunk(document_id, 0)
    return section


def _persona(**overrides: object) -> PersonaSearchInfo:
    values: dict[str, object] = {
        "document_set_names": [],
        "search_start_date": None,
        "attached_document_ids": [],
        "hierarchy_node_ids": [],
    }
    values.update(overrides)
    return PersonaSearchInfo.model_validate(values)


def _make_tool(
    persona: PersonaSearchInfo | None = None,
    user_selected_filters: BaseFilters | None = None,
    project_id_filter: int | None = None,
    persona_id_filter: int | None = None,
    bypass_acl: bool = False,
) -> SearchTool:
    tool = SearchTool.__new__(SearchTool)
    tool.persona_search_info = persona or _persona()
    tool.user_selected_filters = user_selected_filters
    tool.project_id_filter = project_id_filter
    tool.persona_id_filter = persona_id_filter
    tool.bypass_acl = bypass_acl
    return tool


def _scope(
    tool: SearchTool,
    auto_source_scope: list[DocumentSource] | None = None,
    time_filter: TimeFilter | None = None,
    federated_retrieval_infos: list[FederatedRetrievalInfo] | None = None,
    slack_lane_ran: bool = False,
) -> SearchReceiptScope | None:
    return tool._build_receipt_scope(
        auto_source_scope=auto_source_scope,
        time_filter=time_filter,
        federated_retrieval_infos=federated_retrieval_infos or [],
        slack_lane_ran=slack_lane_ran,
    )


class TestLaneCapture:
    def test_lanes_keep_order_duplicates_and_alpha(self) -> None:
        lanes = _build_retrieval_candidate_lanes(
            [("same", None), ("same", 0.2), ("other", None)],
            [
                [_chunk("A", 0), _chunk("A", 1), _chunk("B", 0)],
                [_chunk("A", 3)],
                [],
            ],
        )
        assert [(lane.query, lane.hybrid_alpha) for lane in lanes] == [
            ("same", None),
            ("same", 0.2),
            ("other", None),
        ]
        assert [
            (c.document_id, c.chunk_id, c.rank) for c in lanes[0].returned_chunks
        ] == [
            ("A", 0, 1),
            ("A", 1, 2),
            ("B", 0, 3),
        ]
        assert lanes[2].returned_chunks == []

    def test_lane_count_must_match_results(self) -> None:
        with pytest.raises(ValueError):
            _build_retrieval_candidate_lanes([("q", None)], [])

    def test_post_cap_ids_are_distinct_and_ordered(self) -> None:
        assert _distinct_section_document_ids(
            [_section("B"), _section("A"), _section("B"), _section("C")]
        ) == ["B", "A", "C"]


class TestReceiptScope:
    def test_reports_actual_filters_persona_sets_and_acl(self) -> None:
        tool = _make_tool(
            persona=_persona(document_set_names=["Eng"]),
            user_selected_filters=BaseFilters(
                source_type=[DocumentSource.CONFLUENCE], document_set=["Eng"]
            ),
            bypass_acl=True,
        )
        scope = _scope(tool)
        assert scope is not None
        assert scope.user_filters == {
            "source_type": ["confluence"],
            "document_set": ["Eng"],
            "created_at_range": None,
            "updated_at_range": None,
            "tags": None,
        }
        assert scope.persona_document_sets == ["Eng"]
        assert scope.acl_enforced is False

    def test_default_scope_matches_evaluated_values(self) -> None:
        scope = _scope(_make_tool())
        assert scope is not None
        assert scope.model_dump() == {
            "user_filters": None,
            "persona_document_sets": [],
            "acl_enforced": True,
        }

    @pytest.mark.parametrize(
        ("tool", "overrides"),
        [
            (_make_tool(), {"auto_source_scope": [DocumentSource.SLACK]}),
            (
                _make_tool(),
                {
                    "time_filter": TimeFilter(
                        field=DocumentTimeField.UPDATED_AT,
                        start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    )
                },
            ),
            (
                _make_tool(),
                {"federated_retrieval_infos": [MagicMock(spec=FederatedRetrievalInfo)]},
            ),
            (_make_tool(), {"slack_lane_ran": True}),
            (_make_tool(project_id_filter=7), {}),
            (_make_tool(persona_id_filter=3), {}),
            (
                _make_tool(
                    persona=_persona(
                        search_start_date=datetime(2025, 1, 1, tzinfo=timezone.utc)
                    )
                ),
                {},
            ),
            (_make_tool(persona=_persona(attached_document_ids=["d"])), {}),
            (_make_tool(persona=_persona(hierarchy_node_ids=[1])), {}),
        ],
        ids=[
            "auto_source_scope",
            "auto_time_filter",
            "federated_sources",
            "slack_lane",
            "project_scope",
            "persona_id_filter",
            "persona_start_date",
            "persona_attached_docs",
            "persona_hierarchy_nodes",
        ],
    )
    def test_unrepresentable_scope_gates_receipt_off(
        self, tool: SearchTool, overrides: dict[str, Any]
    ) -> None:
        assert _scope(tool, **overrides) is None


# ---------------------------------------------------------------------------
# SearchTool.run end to end (DB, LLM and retrieval mocked)
# ---------------------------------------------------------------------------

MODULE = "onyx.tools.tool_implementations.search.search_tool"


def _persona_mock() -> MagicMock:
    return MagicMock(
        document_set_names=[],
        search_start_date=None,
        attached_document_ids=[],
        hierarchy_node_ids=[],
    )


def _real_tool(enable_slack_search: bool = False) -> SearchTool:
    return SearchTool(
        tool_id=1,
        emitter=MagicMock(),
        user=MagicMock(is_anonymous=False),
        persona_search_info=_persona_mock(),
        llm=MagicMock(),
        document_index=MagicMock(),
        user_selected_filters=None,
        project_id_filter=None,
        enable_slack_search=enable_slack_search,
        auto_detect_filters=False,
    )


def _run_tool(
    tool: SearchTool,
    *,
    include_retrieval_candidates: bool,
    search_results_by_query: dict[str, list[str]],
    slack_token: str | None = None,
) -> Any:
    """Run tool.run() to the empty-results return with retrieval mocked.

    search_pipeline returns one chunk per document id listed for the query.
    Fusion and merge return nothing, so run() takes the no-results path, which
    still has to attach diagnostics.
    """

    def fake_search_pipeline(**kwargs: Any) -> list[MagicMock]:
        query = kwargs["chunk_search_request"].query
        return [
            _chunk(doc_id, i) for i, doc_id in enumerate(search_results_by_query[query])
        ]

    def fake_prefetch(
        _self: SearchTool, _db_session: Any
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        return slack_token, None, {}

    with (
        patch(f"{MODULE}.get_session_with_current_tenant") as mock_session_ctx,
        patch(f"{MODULE}.build_access_filters_for_user", return_value=[]),
        patch(f"{MODULE}.get_current_search_settings", return_value=MagicMock()),
        patch(f"{MODULE}.EmbeddingModel"),
        patch(f"{MODULE}.get_federated_retrieval_functions", return_value=[]),
        patch(f"{MODULE}.fetch_unique_document_sources", return_value=[]),
        patch(f"{MODULE}.semantic_query_rephrase", return_value="semantic q"),
        patch(f"{MODULE}.keyword_query_expansion", return_value=["keyword q"]),
        patch(f"{MODULE}.weighted_reciprocal_rank_fusion", return_value=[]),
        patch(f"{MODULE}.merge_individual_chunks", return_value=[]),
        patch(f"{MODULE}.search_pipeline", side_effect=fake_search_pipeline),
        patch.object(SearchTool, "_prefetch_slack_data", fake_prefetch),
        patch.object(SearchTool, "_run_slack_search", return_value=[]),
    ):
        mock_session_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)
        return tool.run(
            placement=Placement(turn_index=0, tab_index=0),
            override_kwargs=SearchToolOverrideKwargs(
                starting_citation_num=1,
                original_query="original q",
                message_history=[
                    ChatMinimalTextMessage(
                        message="original q", message_type=MessageType.USER
                    )
                ],
                include_retrieval_candidates=include_retrieval_candidates,
            ),
            queries=["llm q"],
        )


_RESULTS = {
    "llm q": ["A", "A", "B"],
    "semantic q": ["B", "C"],
    "original q": [],
    "keyword q": ["C"],
}


def test_run_captures_lanes_in_execution_order_with_alpha() -> None:
    response = _run_tool(
        _real_tool(),
        include_retrieval_candidates=True,
        search_results_by_query=_RESULTS,
    )
    assert isinstance(response.rich_response, SearchDocsResponse)
    diagnostics = response.rich_response.retrieval_diagnostics
    assert diagnostics is not None
    lanes = diagnostics.retrieval_candidates
    # Semantic lanes (semantic, llm, original) then the keyword lane at alpha 0.2.
    assert [(lane.query, lane.hybrid_alpha) for lane in lanes] == [
        ("semantic q", None),
        ("llm q", None),
        ("original q", None),
        ("keyword q", KEYWORD_QUERY_HYBRID_ALPHA),
    ]
    by_query = {lane.query: lane for lane in lanes}
    assert [c.document_id for c in by_query["llm q"].returned_chunks] == ["A", "A", "B"]
    assert [c.rank for c in by_query["llm q"].returned_chunks] == [1, 2, 3]
    assert by_query["original q"].returned_chunks == []
    # Empty-results path: honest zero after the cap, scope still reported.
    assert diagnostics.merged_candidate_document_ids_after_cap == []
    assert diagnostics.receipt_scope is not None
    assert diagnostics.receipt_scope.model_dump() == {
        "user_filters": None,
        "persona_document_sets": [],
        "acl_enforced": True,
    }
    # No evidence: the original response string is the normal empty result.
    assert response.rich_response.citation_mapping == {}


def test_run_without_request_attaches_no_diagnostics() -> None:
    response = _run_tool(
        _real_tool(),
        include_retrieval_candidates=False,
        search_results_by_query=_RESULTS,
    )
    assert isinstance(response.rich_response, SearchDocsResponse)
    assert response.rich_response.retrieval_diagnostics is None


def test_run_with_slack_lane_excludes_it_and_gates_scope() -> None:
    response = _run_tool(
        _real_tool(enable_slack_search=True),
        include_retrieval_candidates=True,
        search_results_by_query=_RESULTS,
        slack_token="xoxb-test",
    )
    assert isinstance(response.rich_response, SearchDocsResponse)
    diagnostics = response.rich_response.retrieval_diagnostics
    assert diagnostics is not None
    # Four query lanes; the trailing Slack result is not a lane.
    assert [lane.query for lane in diagnostics.retrieval_candidates] == [
        "semantic q",
        "llm q",
        "original q",
        "keyword q",
    ]
    assert diagnostics.receipt_scope is None


def test_tool_runner_threads_capture_flag_into_override_kwargs() -> None:
    tool = _real_tool()
    tool.emit_start = MagicMock()  # type: ignore[method-assign]
    captured: list[SearchToolOverrideKwargs] = []

    def fake_run(**kwargs: Any) -> ToolResponse:
        captured.append(kwargs["override_kwargs"])
        return ToolResponse(
            rich_response=SearchDocsResponse(search_docs=[], citation_mapping={}),
            llm_facing_response="{}",
        )

    run_patch = patch.object(tool, "run", side_effect=fake_run)
    history = [
        ChatMessageSimple(message="q", token_count=1, message_type=MessageType.USER)
    ]
    kickoff = ToolCallKickoff(
        tool_call_id="c1",
        tool_name=SearchTool.NAME,
        tool_args={"queries": ["q"]},
        placement=Placement(turn_index=0, tab_index=0),
    )
    for flag in (False, True):
        with run_patch:
            run_tool_calls(
                tool_calls=[kickoff],
                tools=[tool],
                message_history=history,
                user_memory_context=None,
                user_info=None,
                citation_mapping={},
                next_citation_num=1,
                include_search_retrieval_candidates=flag,
            )
    assert [k.include_retrieval_candidates for k in captured] == [False, True]
