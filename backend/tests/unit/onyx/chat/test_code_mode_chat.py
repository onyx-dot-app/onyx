"""Code mode results render live and on replay, save, and change the offered tools."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from onyx.agents.models import (
    ExecutionStatus,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.agent import ChatAgent
from onyx.chat.checkpoint import CHECKPOINT_PAYLOAD_TYPES, CheckpointSerializer
from onyx.chat.presentation import project_response
from onyx.chat.prompt_utils import build_system_prompt
from onyx.chat.renderer import tool_renderer
from onyx.configs.chat_configs import CODE_MODE_MAX_LLM_CYCLES, MAX_LLM_CYCLES
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import StoredToolResult
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.tool_prompts import (
    CODE_MODE_GUIDANCE,
    INTERNAL_SEARCH_GUIDANCE,
    TOOL_DESCRIPTION_SEARCH_GUIDANCE,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.constants import FILE_READER_TOOL_NAME, WAIT_CODE_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CodeModeExposure,
    CustomToolCallSummary,
    LlmPythonExecutionResult,
    PythonExecutionFile,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    with_code_mode,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeCallFinished,
    CodeModeCallProgress,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
    StoreCommit,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.postgres_sanitization import sanitize_json_like
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM, run_agent
from tests.unit.onyx.tools.code_mode.fakes import search_doc

SUBAGENT_TOOLS = [
    "spawn_agent",
    "list_agents",
    "interrupt_agent",
    "send_message",
    "queue_message",
]

PLACEMENT = Placement(turn_index=1, tab_index=0)
CODE = "r = await internal_search(queries=['q'])\nprint(r)"


DOC_A = search_doc("alpha")
DOC_B = search_doc("beta")

SEARCH_CALL = CodeModeCall(
    id="code-1:0",
    state="ok",
    index=0,
    tool_name=SearchTool.NAME,
    function_name=SearchTool.NAME,
    arguments={"queries": ["q"]},
    content="search results",
    details=SearchDocsResponse(
        queries=["q"],
        search_docs=[DOC_A, DOC_B],
        citation_mapping={1: DOC_A.document_id, 2: DOC_B.document_id},
    ),
)
CUSTOM_CALL = CodeModeCall(
    id="code-1:1",
    state="ok",
    index=1,
    tool_name="lookup",
    function_name="lookup",
    arguments={"id": 7},
    content='{"value": "found"}',
    details=CustomToolCallSummary(
        tool_name="lookup", response_type="json", tool_result={"value": "found"}
    ),
)


def _execution(stdout: str = "alpha\n") -> CodeModeExecutionResult:
    return CodeModeExecutionResult(
        cell_id=1,
        code=CODE,
        status="completed",
        stdout=stdout,
        result="2",
        duration_seconds=1.5,
        calls=[SEARCH_CALL, CUSTOM_CALL],
        commit=StoreCommit(
            ordinal=1, follows=0, writes={"titles": ["Alpha", "Beta"], "old": None}
        ),
        tool_call_count=2,
    )


def _call() -> ToolCall:
    return ToolCall(id="code-1", name=CodeModeTool.NAME, arguments={"code": CODE})


def _result_message(
    details: BaseModel | None = None, *, is_error: bool = False
) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id="code-1",
        tool_name=CodeModeTool.NAME,
        content="program output",
        details=_execution() if details is None and not is_error else details,
        is_error=is_error,
    )


def _shape(output: list[packets.Packet]) -> list[tuple[str, int | None]]:
    return [(packet.obj.type, packet.placement.sub_turn_index) for packet in output]


def _state(result: ToolResultMessage) -> RunState:
    call = _call()
    return RunState(
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


def test_live_code_mode_renders_nested_calls_under_the_code_block() -> None:
    renderer = tool_renderer(_call(), PLACEMENT)
    output = renderer.start()
    for details in [
        CodeModeStdout(text="alpha\n"),
        CodeModeCallStarted(call=SEARCH_CALL),
        CodeModeCallProgress(index=0, details=SEARCH_CALL.details),
        CodeModeCallFinished(call=SEARCH_CALL),
        CodeModeCallStarted(call=CUSTOM_CALL),
        CodeModeCallFinished(call=CUSTOM_CALL),
    ]:
        output += renderer.update(details)
    output += renderer.complete(_result_message())

    assert _shape(output) == [
        ("code_mode_start", None),
        ("code_mode_delta", None),
        ("search_tool_start", 0),
        ("search_tool_queries_delta", 0),
        ("search_tool_filter_delta", 0),
        ("search_tool_documents_delta", 0),
        ("search_tool_filter_delta", 0),
        ("section_end", 0),
        ("custom_tool_start", 1),
        ("custom_tool_args", 1),
        ("custom_tool_delta", 1),
        ("section_end", 1),
        ("code_mode_delta", None),
        ("section_end", None),
    ]
    assert all(
        packet.placement.turn_index == 1 and packet.placement.tab_index == 0
        for packet in output
    )
    start = output[0].obj
    assert isinstance(start, packets.CodeModeStart) and start.code == CODE
    final = output[-2].obj
    assert isinstance(final, packets.CodeModeDelta)
    # Live stdout already streamed; the final delta carries only the status.
    assert final.stdout == ""
    assert (final.status, final.result, final.tool_call_count) == ("completed", "2", 2)
    documents = [
        packet.obj.documents
        for packet in output
        if isinstance(packet.obj, packets.SearchToolDocumentsDelta)
    ]
    assert documents == [[DOC_A, DOC_B]]
    # The nested custom call renders its saved result.
    [custom] = [
        packet.obj
        for packet in output
        if isinstance(packet.obj, packets.CustomToolDelta)
    ]
    assert custom.data == {"value": "found"}
    # Packets after completion are dropped; completion is idempotent.
    assert renderer.update(CodeModeStdout(text="late")) == []
    assert renderer.complete(_result_message()) == []


def test_interrupted_code_mode_closes_open_nested_calls() -> None:
    renderer = tool_renderer(_call(), PLACEMENT)
    renderer.start()
    renderer.update(CodeModeCallStarted(call=SEARCH_CALL))
    output = renderer.complete(None)
    assert _shape(output) == [
        ("section_end", 0),
        ("code_mode_delta", None),
        ("section_end", None),
    ]
    final = output[1].obj
    assert isinstance(final, packets.CodeModeDelta)
    assert (final.status, final.tool_call_count) == ("cancelled", 1)


def test_failed_code_mode_without_details_reports_the_error() -> None:
    renderer = tool_renderer(_call(), PLACEMENT)
    output = renderer.complete(_result_message(is_error=True))
    final = output[-2].obj
    assert isinstance(final, packets.CodeModeDelta)
    assert (final.status, final.error) == ("failed", "program output")


def test_code_mode_result_survives_storage_and_checkpoints() -> None:
    execution = _execution(stdout="a\x00b").model_copy(
        update={
            "calls": [
                *_execution().calls,
                CodeModeCall(
                    id="code-1:2",
                    state="ok",
                    index=2,
                    tool_name="run_python",
                    function_name="run_python",
                    arguments={"code": "print(1)"},
                    details=LlmPythonExecutionResult(
                        stdout="1",
                        stderr="",
                        exit_code=0,
                        timed_out=False,
                        generated_files=[],
                        error=None,
                    ),
                ),
            ]
        }
    )
    message = _result_message(execution)
    stored = StoredToolResult.model_validate(
        sanitize_json_like(
            StoredToolResult.model_validate(message, from_attributes=True).model_dump(
                mode="json"
            )
        )
    )
    assert isinstance(stored.details, CodeModeExecutionResult)
    assert stored.details.stdout == "ab"
    assert stored.details.calls == execution.calls
    assert stored.details.commit == execution.commit

    serializer = CheckpointSerializer(CHECKPOINT_PAYLOAD_TYPES)
    assert serializer.decode_payload(serializer.encode_payload(execution)) == execution


def test_nested_artifacts_belong_to_the_code_mode_call() -> None:
    file = PythonExecutionFile(filename="chart.png", file_link="/api/chat/file/abc")
    execution = _execution().model_copy(
        update={
            "calls": [
                CodeModeCall(
                    id="code-1:0",
                    state="ok",
                    index=0,
                    tool_name="run_python",
                    function_name="run_python",
                    arguments={},
                    details=LlmPythonExecutionResult(
                        stdout="",
                        stderr="",
                        exit_code=0,
                        timed_out=False,
                        generated_files=[file],
                        error=None,
                    ),
                )
            ]
        }
    )
    history = project_response(
        _state(_result_message(execution)), tool_ids={CodeModeTool.NAME: None}
    )
    assert history.tool_calls[0].generated_files == [file]


def test_direct_search_prompt_has_no_code_mode_guidance() -> None:
    # Code mode guidance is checked through a real chat in
    # external_dependency_unit/answer/test_code_mode_citations.py.
    search = MagicMock(spec=SearchTool)
    search.name = SearchTool.NAME
    direct = build_system_prompt("base", tools=[search], include_user_info=False)
    assert CODE_MODE_GUIDANCE not in direct
    assert INTERNAL_SEARCH_GUIDANCE in direct
    assert TOOL_DESCRIPTION_SEARCH_GUIDANCE in direct


def test_the_token_reservation_counts_code_mode_guidance() -> None:
    reserved = build_system_prompt(
        "base", include_all_guidance=True, include_user_info=False
    )
    assert CODE_MODE_GUIDANCE in reserved


class _DirectOnlyTool(EchoTool):
    """A tool that waits for a child run, which a program cannot do."""

    def __init__(self) -> None:
        super().__init__()
        self.result_from_children = lambda *_: ToolResult(content="done")

    @property
    def id(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT


class _NestedChildRunTool(_DirectOnlyTool):
    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE


class _LookupTool(EchoTool):
    @property
    def id(self) -> int:
        return 3

    @property
    def name(self) -> str:
        return "lookup"


def test_function_tools_move_into_execute_code() -> None:
    offered, cells = with_code_mode([EchoTool(), _DirectOnlyTool(), _LookupTool()])
    assert cells is not None
    assert [tool.name for tool in offered] == [
        "send_email",
        CodeModeTool.NAME,
        WAIT_CODE_TOOL_NAME,
    ]
    code_mode = offered[1]
    assert [tool.name for tool in code_mode.inner_tools] == ["echo", "lookup"]
    assert not offered[2].inner_tools
    assert [tool.id for tool in offered[1:]] == [None, None]


def test_without_function_tools_the_tools_stay_direct() -> None:
    tools: list[Tool] = [_DirectOnlyTool()]
    assert with_code_mode(tools) == (tools, None)


def test_a_tool_that_waits_for_child_runs_must_be_direct() -> None:
    with pytest.raises(ValueError, match="send_email"):
        with_code_mode([EchoTool(), _NestedChildRunTool()])


def _context_files() -> ExtractedContextFiles:
    return ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=None,
    )


def _offered(request: dict[str, Any]) -> list[str]:
    return [tool["function"]["name"] for tool in request["tools"]]


@pytest.mark.parametrize(
    ("preferred_tool_id", "operation"),
    [
        # A function runs only inside programs, so the preference names it so.
        (EchoTool().id, "echo (a function in `execute_code` programs)"),
        (_DirectOnlyTool().id, "send_email"),
    ],
)
def test_code_mode_names_preferred_tools_without_changing_definitions(
    preferred_tool_id: int, operation: str
) -> None:
    llm = ScriptedLLM([Delta(content="Done.")])
    agent = ChatAgent(
        messages=[],
        tools=[EchoTool(), _DirectOnlyTool(), _LookupTool()],
        code_mode=True,
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,
        token_counter=len,
        preferred_tool_id=preferred_tool_id,
    )
    run_agent(agent, messages=[UserMessage(content="Find")], max_steps=3)

    [request] = llm.requests
    assert _offered(request) == [
        "send_email",
        CodeModeTool.NAME,
        WAIT_CODE_TOOL_NAME,
        *SUBAGENT_TOOLS,
    ]
    assert request["tool_choice"] == ToolChoiceOptions.AUTO
    assert f"selected these operations for this request: {operation}." in str(request)


def test_code_mode_keeps_identical_tool_definitions_on_the_final_step() -> None:
    program = Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                index=0,
                id="call-0",
                function=ResponseFunctionCall(
                    name=CodeModeTool.NAME, arguments='{"code": "print(1)"}'
                ),
            )
        ]
    )
    llm = ScriptedLLM([program, Delta(content="Done.")])
    agent = ChatAgent(
        messages=[],
        tools=[EchoTool(), _DirectOnlyTool()],
        code_mode=True,
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,
        token_counter=len,
    )
    run_agent(agent, messages=[UserMessage(content="Find")], max_steps=2)

    first, final = llm.requests
    assert first["tools"] == final["tools"]
    assert _offered(final) == [
        "send_email",
        CodeModeTool.NAME,
        WAIT_CODE_TOOL_NAME,
        *SUBAGENT_TOOLS,
    ]
    assert final["tool_choice"] == ToolChoiceOptions.NONE


@pytest.mark.parametrize(
    ("code_mode", "tools", "step_cap"),
    [
        (False, [EchoTool()], MAX_LLM_CYCLES),
        (True, [EchoTool()], CODE_MODE_MAX_LLM_CYCLES),
        # No tool runs inside programs, so code mode does not apply.
        (True, [_DirectOnlyTool()], MAX_LLM_CYCLES),
    ],
)
def test_the_code_mode_step_cap_applies_when_code_mode_does(
    code_mode: bool, tools: list[Tool], step_cap: int
) -> None:
    agent = ChatAgent(
        messages=[],
        tools=tools,
        code_mode=code_mode,
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=ScriptedLLM([]),
        token_counter=len,
    )
    assert agent.max_steps == step_cap
    assert CODE_MODE_MAX_LLM_CYCLES >= MAX_LLM_CYCLES


class _ReadFileTool(EchoTool):
    @property
    def name(self) -> str:
        return FILE_READER_TOOL_NAME


def test_the_file_notice_names_a_tool_that_runs_inside_programs() -> None:
    llm = ScriptedLLM([Delta(content="Done.")])
    agent = ChatAgent(
        messages=[],
        tools=[_ReadFileTool()],
        code_mode=True,
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,
        token_counter=len,
        all_injected_file_metadata={
            "file-1": FileToolMetadata(
                file_id="file-1", filename="report.pdf", approx_char_count=90_000
            )
        },
    )
    run_agent(agent, messages=[UserMessage(content="Summarize")], max_steps=3)

    [request] = llm.requests
    assert _offered(request) == [
        CodeModeTool.NAME,
        WAIT_CODE_TOOL_NAME,
        *SUBAGENT_TOOLS,
    ]
    assert "Use the read_file tool" in str(request)
    assert 'file_id="file-1"' in str(request)


def test_nested_custom_tools_carry_their_tool_id_live_and_on_replay() -> None:
    call = CUSTOM_CALL.model_copy(update={"tool_id": 9})
    live = tool_renderer(_call(), PLACEMENT)
    output = live.start()
    output += live.update(CodeModeCallStarted(call=call))
    output += live.update(CodeModeCallFinished(call=call))
    replayed = tool_renderer(_call(), PLACEMENT).complete(
        _result_message(_execution().model_copy(update={"calls": [call]}))
    )
    for packet_list in (output, replayed):
        tool_ids = [
            packet.obj.tool_id
            for packet in packet_list
            if isinstance(
                packet.obj, (packets.CustomToolStart, packets.CustomToolDelta)
            )
        ]
        assert tool_ids == [9, 9]


def test_live_stdout_cut_at_the_limit_is_replaced_by_the_saved_stdout() -> None:
    saved = "head\n... [output truncated, 10 characters omitted] ...\ntail\n"
    renderer = tool_renderer(_call(), PLACEMENT)
    renderer.start()
    renderer.update(
        CodeModeStdout(text="head\n... [further output is not shown live]\n")
    )
    final = renderer.complete(_result_message(_execution(stdout=saved)))[-2].obj
    assert isinstance(final, packets.CodeModeDelta)
    assert (final.stdout, final.replace_stdout) == (saved, True)

    replayed = (
        tool_renderer(_call(), PLACEMENT)
        .complete(_result_message(_execution(stdout=saved)))[-2]
        .obj
    )
    assert isinstance(replayed, packets.CodeModeDelta)
    assert (replayed.stdout, replayed.replace_stdout) == (saved, False)
