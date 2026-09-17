"""Saved tool output supports historical summaries and current result metadata."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from onyx.chat.artifacts import _saved_tool_metadata
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import Tool, ToolCall
from onyx.llm.models import ToolResultMessage
from onyx.server.query_and_chat.session_loading import _saved_tool_item
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    LlmPythonExecutionResult,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool


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
    item = _saved_tool_item(
        call, Tool(name="python", in_code_tool_id=PythonTool.__name__)
    )
    output = item.metadata
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
    output = _saved_tool_item(call, tool).metadata
    assert isinstance(output, CustomToolCallSummary)
    assert CustomToolUserFileSnapshot.model_validate(output.tool_result).file_ids == [
        "report.csv"
    ]
    call.tool_call_response = (
        '{"tool_name":"export","response_type":"csv","tool_result":{"file_ids":[42]}}'
    )
    with pytest.raises(ValidationError):
        _saved_tool_item(call, tool)


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
    restored = _saved_tool_item(
        call, Tool(name="internal_search", in_code_tool_id=SearchTool.__name__)
    ).metadata
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
        _saved_tool_item(call, Tool(name="tool", in_code_tool_id=implementation))


def test_legacy_search_model_output_uses_saved_arguments() -> None:
    call = ToolCall(
        tool_id=1,
        tool_call_arguments={"queries": ["question"]},
        tool_call_response='{"type":"internal_search","results":[]}',
        search_docs=[],
    )
    result = _saved_tool_item(
        call, Tool(name="internal_search", in_code_tool_id=SearchTool.__name__)
    ).metadata
    assert isinstance(result, SearchDocsResponse)
    assert result.queries == ["question"]
