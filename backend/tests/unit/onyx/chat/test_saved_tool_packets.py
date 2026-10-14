"""Saved SDK results render without tool definitions; legacy history keeps its reader."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pydantic import BaseModel, JsonValue
from sqlalchemy.orm import Session

from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import RunState, StepRecord, ToolExecutionRecord
from onyx.chat.models import ChatSearchResult
from onyx.chat.presentation import _collect_tool_history
from onyx.chat.renderer import ToolRenderer
from onyx.chat.response import response_record
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SavedSearchDoc, SearchDoc, SearchDocsResponse
from onyx.db.models import ChatMessage, StoredToolResult, Tool, ToolCall
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.llm.models import AssistantMessage, ToolResultMessage
from onyx.llm.models import ToolCall as ModelToolCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import (
    _response_packets,
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    CustomToolDelta,
    MemoryToolNoAccess,
    OverallStop,
    PacketException,
    ReasoningDelta,
    SearchToolDocumentsDelta,
)
from onyx.tools.models import (
    ChatFile,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool


@pytest.mark.parametrize(
    "kind", ["search", "custom", "error", "display_error", "no_details"]
)
def test_live_and_saved_tool_cards_share_public_content_without_tool_definition(
    kind: str,
) -> None:
    call = ModelToolCall(
        id="call",
        name="lookup",
        arguments={"queries": ["question"], "requestBody": "private input"},
    )
    details: BaseModel | None
    if kind == "search":
        details = ChatSearchResult(
            queries=["question"],
            sources=["file"],
            time_filter_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            search_docs=[],
            citation_mapping={},
            staged_files=[ChatFile(filename="private.txt", content=b"private content")],
        )
    elif kind == "custom":
        details = CustomToolCallSummary(
            tool_name="lookup", response_type="json", tool_result={"value": "found"}
        )
    elif kind == "display_error":
        details = ToolExecutionError(message="lookup failed")
    else:
        details = None
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="lookup failed" if "error" in kind else "model output",
        details=details,
        is_error="error" in kind,
    )
    renderer = ToolRenderer(call, Placement(turn_index=0), tool_id=1)
    live = renderer.start() + renderer.complete(result)
    response = response_record(
        RunState(
            run_id="run",
            status=RunStatus.COMPLETE,
            steps=[
                StepRecord(
                    message=AssistantMessage(id="run:0", content=[call]),
                    generation_status=ExecutionStatus.COMPLETE,
                    tools={
                        call.id: ToolExecutionRecord(
                            status=ExecutionStatus.COMPLETE, result=result
                        )
                    },
                )
            ],
        )
    )
    stored = response.steps[0].tools[call.id].result
    assert stored is not None
    response.steps[0].tools[call.id].result = StoredToolResult.model_validate_json(
        stored.model_dump_json()
    )
    record = ToolCall(
        id=1,
        tool_id=1,
        tool_call_arguments=call.arguments,
        search_docs=[],
        tool_call_response='{"type":"search_result","queries":["stale"]}',
    )
    restored = _response_packets(response, {("run:0", call.id): record}, {}, {})
    assert [
        packet.model_dump()
        for packet in restored
        if not isinstance(packet.obj, OverallStop)
    ] == [packet.model_dump() for packet in live]
    public_json = "".join(packet.model_dump_json() for packet in restored)
    assert "staged_files" not in public_json
    assert "private" not in public_json
    assert "stale" not in public_json
    if kind == "error":
        errors = [
            packet.obj for packet in restored if isinstance(packet.obj, CustomToolDelta)
        ]
        assert errors[-1].data == "lookup failed"
    if kind == "display_error":
        errors = [
            packet.obj for packet in restored if isinstance(packet.obj, PacketException)
        ]
        assert len(errors) == 1
        assert str(errors[0].exception) == "lookup failed"


@pytest.mark.parametrize(
    ("response_type", "payload"),
    [
        ("json", {"file_ids": ["report"], "other": 1}),
        ("json", {"file_ids": ["report"]}),
        ("image", {"file_ids": ["report"]}),
        ("csv", {"file_ids": ["report"]}),
    ],
)
def test_custom_result_file_type_survives_storage(
    response_type: str, payload: dict[str, JsonValue]
) -> None:
    call = ModelToolCall(id="call", name="custom", arguments={})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="model output",
        details=CustomToolCallSummary(
            tool_name=call.name, response_type=response_type, tool_result=payload
        ),
    )
    stored = StoredToolResult.model_validate_json(result.model_dump_json())
    assert isinstance(stored.details, CustomToolCallSummary)
    if response_type == "json":
        assert stored.details.tool_result == payload
    else:
        assert isinstance(stored.details.tool_result, CustomToolUserFileSnapshot)
        assert stored.details.tool_result.file_ids == ["report"]
    live_packets = ToolRenderer(call, Placement(turn_index=0)).complete(result)
    saved_packets = ToolRenderer(call, Placement(turn_index=0)).complete(stored)
    assert [packet.model_dump() for packet in saved_packets] == [
        packet.model_dump() for packet in live_packets
    ]


@pytest.mark.parametrize("select_none", [False, True])
def test_saved_search_selection_uses_document_links_without_mutating_result(
    select_none: bool,
) -> None:
    doc = SearchDoc(
        document_id="retrieved",
        chunk_ind=0,
        semantic_identifier="Retrieved document",
        blurb="content",
        source_type=DocumentSource.FILE,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    call = ModelToolCall(id="search-1", name=SearchTool.NAME, arguments={})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="result",
        details=SearchDocsResponse(
            search_docs=[doc],
            displayed_docs=[] if select_none else None,
            citation_mapping={},
        ),
    )
    state = RunState(
        run_id="run",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(id="message", content=[call]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    call.id: ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE, result=result
                    )
                },
            )
        ],
    )
    history = _collect_tool_history(state, {call.name: 1})
    assert history.tool_calls[0].search_docs == ([] if select_none else [doc])
    response = response_record(state)
    saved_result = response.steps[0].tools[call.id].result
    assert saved_result is not None
    saved_result = StoredToolResult.model_validate_json(saved_result.model_dump_json())
    response.steps[0].tools[call.id].result = saved_result
    before = saved_result.model_dump_json()
    record = ToolCall(
        tool_id=1,
        search_docs=[]
        if select_none
        else [
            DbSearchDoc(
                id=42,
                document_id=doc.document_id,
                chunk_ind=0,
                semantic_id=doc.semantic_identifier,
                blurb=doc.blurb,
                source_type=doc.source_type,
                boost=1,
                hidden=False,
                doc_metadata={},
                match_highlights=[],
                is_internet=False,
            )
        ],
    )
    packets = _response_packets(response, {("message", call.id): record}, {}, {})
    documents = [
        doc
        for packet in packets
        if isinstance(packet.obj, SearchToolDocumentsDelta)
        for doc in packet.obj.documents
    ]
    assert [doc.document_id for doc in documents] == (
        [] if select_none else ["retrieved"]
    )
    if documents:
        assert isinstance(documents[0], SavedSearchDoc)
        assert documents[0].db_doc_id == 42
    assert saved_result.model_dump_json() == before


@pytest.mark.parametrize("display_error", [False, True])
def test_image_failure_renders_error_at_tool_placement(display_error: bool) -> None:
    placement = Placement(turn_index=2, tab_index=1, model_index=1)
    call = ModelToolCall(id="image", name=ImageGenerationTool.NAME, arguments={})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="Tool failed with error: The image request was rejected by the content policy.",
        is_error=True,
        details=ToolExecutionError(
            message="The image request was rejected by the content policy."
        )
        if display_error
        else None,
    )
    packets = ToolRenderer(call, placement).complete(result)
    errors = [packet for packet in packets if isinstance(packet.obj, PacketException)]
    assert len(errors) == int(display_error)
    assert all(packet.placement == placement for packet in packets)
    assert packets[-1].obj.type == "section_end"
    if errors:
        assert isinstance(errors[0].obj, PacketException)
        assert errors[0].model_dump()["obj"] == {"type": "error"}
        assert (
            str(errors[0].obj.exception)
            == "The image request was rejected by the content policy."
        )


def test_memory_failure_does_not_claim_access_was_denied() -> None:
    call = ModelToolCall(id="memory", name="add_memory", arguments={})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="Tool failed with error: memory provider unavailable",
        is_error=True,
    )
    packets = ToolRenderer(call, Placement(turn_index=0)).complete(result)
    assert not any(
        isinstance(packet.obj, (MemoryToolNoAccess, PacketException))
        for packet in packets
    )
    assert packets[-1].obj.type == "section_end"


@pytest.mark.parametrize(
    (
        "first_reasoning",
        "second_reasoning",
        "final_reasoning",
        "expected",
        "final_turn",
    ),
    [
        (
            "First parallel thought",
            "Second parallel thought",
            "Final thought",
            [("First parallel thought", 1), ("Final thought", 3)],
            4,
        ),
        (
            None,
            "Second parallel thought",
            "Final thought",
            [("Second parallel thought", 1), ("Final thought", 3)],
            4,
        ),
        (
            "",
            "Second parallel thought",
            "Final thought",
            [("Second parallel thought", 1), ("Final thought", 3)],
            4,
        ),
        (None, None, None, [], 3),
    ],
)
def test_legacy_thinking_precedes_tool_groups_and_final_answer(
    first_reasoning: str | None,
    second_reasoning: str | None,
    final_reasoning: str | None,
    expected: list[tuple[str, int]],
    final_turn: int,
) -> None:
    response = ChatMessage(
        id=10,
        message="Final answer",
        message_type=MessageType.ASSISTANT,
        response_status=None,
        reasoning_tokens=final_reasoning,
        citations=None,
        search_docs=[],
        tool_calls=[
            ToolCall(
                id=call_id,
                tool_id=1,
                turn_number=2,
                tab_index=index,
                tool_call_arguments={},
                tool_call_response="Tool output",
                reasoning_tokens=first_reasoning if index == 0 else second_reasoning,
            )
            for index, call_id in enumerate((11, 12))
        ],
    )
    with (
        Session() as session,
        patch(
            "onyx.server.query_and_chat.session_loading.get_tool_by_id",
            return_value=Tool(name="lookup", display_name="Lookup"),
        ),
    ):
        packets = translate_assistant_message_to_packets(response, session)

    assert [
        (packet.obj.reasoning, packet.placement.turn_index)
        for packet in packets
        if isinstance(packet.obj, ReasoningDelta)
    ] == expected
    assert [
        (packet.obj.content, packet.placement.turn_index)
        for packet in packets
        if isinstance(packet.obj, AgentResponseDelta)
    ] == [("Final answer", final_turn)]
    assert isinstance(packets[-1].obj, OverallStop)
    assert packets[-1].placement.turn_index == final_turn
