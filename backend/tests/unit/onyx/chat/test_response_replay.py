"""Saved response replay uses durable identities and the live packet renderers."""

import pytest

from onyx.agents.models import (
    ExecutionStatus,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.models import ResponseRecord, ToolReplayData
from onyx.chat.presentation import project_response, replay_response
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.models import AssistantMessage, TextContent, ToolCall, ToolResultMessage
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    OverallStop,
    SearchToolDocumentsDelta,
)


def test_missing_message_identity_preserves_content_without_inventing_tool_records() -> (
    None
):
    message = AssistantMessage(
        content=[
            TextContent(text="Accepted text"),
            ToolCall(id="call", name="internal_search", arguments={}),
        ]
    )
    state = RunState(
        run_id="run",
        status=RunStatus.COMPLETE,
        answer_step_index=0,
        steps=[StepRecord(message=message, generation_status=ExecutionStatus.COMPLETE)],
    )
    projected = project_response(state, tool_ids={"internal_search": 1})
    assert projected.error is not None
    assert projected.response is not None
    assert projected.response.steps[0].message == message
    assert projected.answer == "Accepted text"
    assert projected.tool_calls == []
    assert projected.presentation == {}
    with pytest.raises(ValueError, match="has no identity"):
        replay_response(projected.response, {}, {}, {})


def test_replay_restores_saved_search_documents_and_parent_tabs_without_mutation() -> (
    None
):
    document = SearchDoc(
        document_id="doc",
        chunk_ind=0,
        semantic_identifier="Source",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    calls = [
        ToolCall(id="research", name="research_agent", arguments={"task": "Research"}),
        ToolCall(id="search", name="internal_search", arguments={"queries": ["topic"]}),
    ]
    response = ResponseRecord(
        run_id="root",
        status=RunStatus.CANCELLED,
        steps=[
            StepRecord(
                message=AssistantMessage(id="root-message", content=calls),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "search": ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_call_id="search",
                            tool_name="internal_search",
                            content="Evidence",
                            details=SearchDocsResponse(
                                queries=["topic"],
                                search_docs=[],
                                citation_mapping={1: "doc"},
                            ),
                        ),
                    )
                },
            )
        ],
        child_runs=[
            ResponseRecord(
                run_id="child",
                parent_run_id="root",
                parent_message_id="root-message",
                parent_tool_call_id="research",
                status=RunStatus.COMPLETE,
                steps=[
                    StepRecord(
                        message=AssistantMessage(
                            id="child-message",
                            content=[TextContent(text="Child answer")],
                        ),
                        generation_status=ExecutionStatus.COMPLETE,
                    )
                ],
            )
        ],
    )
    tool = ToolReplayData(tool_id=1, search_docs=[document])
    before = response.model_dump_json()
    packets = replay_response(
        response, {("root-message", "search"): tool}, {}, {"doc": document}
    )
    assert response.model_dump_json() == before
    sources = [
        packet.obj
        for packet in packets
        if isinstance(packet.obj, SearchToolDocumentsDelta)
    ]
    assert len(sources) == 1
    assert sources[0].documents == [document]
    child = next(
        packet
        for packet in packets
        if isinstance(packet.obj, AgentResponseDelta)
        and packet.obj.content == "Child answer"
    )
    assert child.placement.tab_index == 0
    assert child.placement.sub_turn_index is not None
    stops = [packet.obj for packet in packets if isinstance(packet.obj, OverallStop)]
    assert len(stops) == 1
    assert stops[0].stop_reason == "user_cancelled"
