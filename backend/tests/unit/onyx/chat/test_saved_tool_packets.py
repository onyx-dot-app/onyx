"""Saved tool output supports historical summaries and current result metadata."""

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ValidationError

from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import (
    RunState,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.models import ChatSearchResult
from onyx.chat.presentation import _saved_tool_metadata
from onyx.chat.renderer import ToolRenderer
from onyx.chat.response import response_record
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import Tool, ToolCall
from onyx.db.tools import restore_tool_result
from onyx.llm.models import AssistantMessage, ToolResultMessage
from onyx.llm.models import ToolCall as ModelToolCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import (
    _response_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    CustomToolDelta,
    OverallStop,
)
from onyx.tools.models import (
    ChatFile,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    LlmPythonExecutionResult,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def _restored_result(call: ToolCall, tool: Tool) -> ToolResultMessage:
    return restore_tool_result(
        ToolResultMessage(
            tool_call_id=str(call.id),
            tool_name=tool.name,
            content=call.tool_call_response or "",
        ),
        call,
        tool,
    )


@pytest.mark.parametrize(
    "response, expected_stdout, expected_files",
    [
        (
            '{"stdout":"report ready","generated_files":[{"file_link":"/api/chat/file/report.csv"}]}',
            "report ready",
            ["report.csv"],
        ),
        ("execution output", "execution output", []),
    ],
)
def test_python_history_reads_partial_summaries_and_text(
    response: str, expected_stdout: str, expected_files: list[str]
) -> None:
    call = ToolCall(
        tool_id=1,
        turn_number=0,
        tab_index=0,
        tool_call_arguments={"code": "print('report ready')"},
        tool_call_response=response,
    )
    item = _restored_result(
        call, Tool(name="python", in_code_tool_id=PythonTool.__name__)
    )
    output = item.details
    assert isinstance(output, LlmPythonExecutionResult)
    assert output.stdout == expected_stdout
    assert [file.filename for file in output.generated_files] == expected_files


def test_custom_file_history_validates_references() -> None:
    call = ToolCall(
        tool_id=1,
        turn_number=0,
        tab_index=0,
        tool_call_arguments={},
        tool_call_response='{"tool_name":"export","response_type":"csv","tool_result":{"file_ids":["report.csv"]}}',
    )
    tool = Tool(name="export", display_name="Export", in_code_tool_id=None)
    output = _restored_result(call, tool).details
    assert isinstance(output, CustomToolCallSummary)
    assert CustomToolUserFileSnapshot.model_validate(output.tool_result).file_ids == [
        "report.csv"
    ]
    call.tool_call_response = (
        '{"tool_name":"export","response_type":"csv","tool_result":{"file_ids":[42]}}'
    )
    with pytest.raises(ValidationError):
        _restored_result(call, tool)


def test_search_metadata_survives_storage() -> None:
    details = SearchDocsResponse(
        queries=["expanded query"],
        sources=["file"],
        search_docs=[],
        citation_mapping={1: "doc-id"},
        time_filter_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    response = ToolResultMessage(
        tool_call_id="search-1",
        tool_name="internal_search",
        content="model search output",
        details=details,
    )
    metadata = _saved_tool_metadata(response)
    assert metadata is not None
    call = ToolCall(
        tool_id=1,
        turn_number=0,
        tab_index=0,
        tool_call_arguments={"queries": ["original query"]},
        tool_call_response=metadata.model_dump_json(),
        search_docs=[],
    )
    restored = _restored_result(
        call, Tool(name="internal_search", in_code_tool_id=SearchTool.__name__)
    ).details
    assert isinstance(restored, SearchDocsResponse)
    assert restored == details


@pytest.mark.parametrize(
    "implementation, output",
    [
        (PythonTool.__name__, '{"type":"python_execution","stdout":"partial"}'),
        (SearchTool.__name__, '{"type":"search_result","queries":42}'),
    ],
)
def test_corrupt_structured_metadata_is_rejected(
    implementation: str, output: str
) -> None:
    call = ToolCall(
        tool_id=1, tool_call_arguments={}, tool_call_response=output, search_docs=[]
    )
    with pytest.raises(ValidationError):
        _restored_result(call, Tool(name="tool", in_code_tool_id=implementation))


def test_legacy_search_model_output_uses_saved_arguments() -> None:
    call = ToolCall(
        tool_id=1,
        tool_call_arguments={"queries": ["question"]},
        tool_call_response='{"type":"internal_search","results":[]}',
        search_docs=[],
    )
    result = _restored_result(
        call, Tool(name="internal_search", in_code_tool_id=SearchTool.__name__)
    ).details
    assert isinstance(result, SearchDocsResponse)
    assert result.queries == ["question"]


@pytest.mark.parametrize("kind", ["search", "custom", "error"])
def test_live_and_saved_tool_cards_share_public_content(kind: str) -> None:
    call = ModelToolCall(
        id="call",
        name="lookup",
        arguments={"queries": ["question"], "requestBody": "private input"},
    )
    details: BaseModel | None
    if kind == "search":
        details = ChatSearchResult(
            queries=["question"],
            search_docs=[],
            citation_mapping={},
            staged_files=[ChatFile(filename="private.txt", content=b"private content")],
        )
    elif kind == "custom":
        details = CustomToolCallSummary(
            tool_name="lookup", response_type="json", tool_result={"value": "found"}
        )
    else:
        details = None
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="lookup failed" if kind == "error" else "model output",
        details=details,
        is_error=kind == "error",
    )
    renderer = ToolRenderer(call, Placement(turn_index=0), tool_id=1)
    live = renderer.start() + renderer.complete(result)

    metadata = _saved_tool_metadata(result)
    record = ToolCall(
        id=1,
        tool_id=1,
        tool_call_arguments=call.arguments,
        tool_call_response=metadata.model_dump_json() if metadata else result.text,
        search_docs=[],
    )
    status = RunStatus.ERROR if result.is_error else RunStatus.COMPLETE
    response = response_record(
        RunState(
            run_id="run",
            status=status,
            steps=[
                StepRecord(
                    message=AssistantMessage(id="run:0", content=[call]),
                    generation_status=ExecutionStatus.COMPLETE,
                    tools={
                        call.id: ToolExecutionRecord(
                            status=ExecutionStatus(status.value), result=result
                        )
                    },
                )
            ],
        )
    )
    restored = _response_packets(
        response,
        {("run:0", call.id): record},
        {
            1: Tool(
                name=call.name,
                in_code_tool_id=SearchTool.__name__ if kind == "search" else None,
            )
        },
        {},
        {},
    )
    assert [
        packet.obj for packet in restored if not isinstance(packet.obj, OverallStop)
    ] == [packet.obj for packet in live]
    public_json = "".join(packet.model_dump_json() for packet in live)
    assert "staged_files" not in public_json
    assert "private" not in public_json
    if kind == "error":
        errors = [
            packet.obj for packet in live if isinstance(packet.obj, CustomToolDelta)
        ]
        assert errors[-1].data == "lookup failed"
