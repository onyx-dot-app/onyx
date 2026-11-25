"""Code mode results render live and on replay, save, and change the offered tools."""

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

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
from onyx.chat.prompt_utils import build_system_prompt, calculate_reserved_tokens
from onyx.chat.renderer import tool_renderer
from onyx.configs.chat_configs import CODE_MODE_MAX_LLM_CYCLES, MAX_LLM_CYCLES
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import StoredToolResult
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.model_capabilities import ToolFamily
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
    MEMORY_GUIDANCE,
    TOOL_DESCRIPTION_SEARCH_GUIDANCE,
    TOOL_SECTION_HEADER,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.constants import (
    EXEC_TOOL_NAME,
    FILE_READER_TOOL_NAME,
    OPEN_URL_TOOL_NAME,
    WAIT_TOOL_NAME,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CapabilityEntry,
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
from onyx.tools.tool_implementations.code_mode.shapes import (
    CODE_MODE_SHAPES,
    OPENAI_CODE_MODE,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.postgres.postgres_tool import PostgresTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    SANDBOX_TOOLS,
    ApplyPatchTool,
    ExecCommandTool,
    WriteStdinTool,
)
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.postgres_sanitization import sanitize_json_like
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM, run_agent
from tests.unit.onyx.tools.code_mode.fakes import search_doc

PLACEMENT = Placement(turn_index=1, tab_index=0)
CODE = "r = await tools.internal_search(queries=['q'])\nprint(r)"


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
    return ToolCall(id="code-1", name=EXEC_TOOL_NAME, arguments={"code": CODE})


def _result_message(
    details: BaseModel | None = None, *, is_error: bool = False
) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id="code-1",
        tool_name=EXEC_TOOL_NAME,
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
        _state(_result_message(execution)), tool_ids={EXEC_TOOL_NAME: None}
    )
    assert history.tool_calls[0].generated_files == [file]


def test_direct_search_prompt_has_no_code_mode_guidance() -> None:
    # Code mode guidance is checked through a real chat in
    # external_dependency_unit/answer/test_code_mode_citations.py.
    search = MagicMock(spec=SearchTool)
    search.name = SearchTool.NAME
    search.rank = SearchTool.rank
    direct = build_system_prompt("base", tools=[search], include_user_info=False)
    for shape in CODE_MODE_SHAPES.values():
        assert CODE_MODE_GUIDANCE.format(name=shape.run_name) not in direct
    assert INTERNAL_SEARCH_GUIDANCE.format(name=SearchTool.NAME) in direct
    assert TOOL_DESCRIPTION_SEARCH_GUIDANCE in direct


def _code_mode_prompt(offered: list[Tool]) -> str:
    """The system prompt of an agent with `offered`, which names tools as
    the agent's code mode tool, if any, calls them."""
    code = next((tool for tool in offered if isinstance(tool, CodeModeTool)), None)
    return build_system_prompt(
        "base",
        tools=offered,
        include_user_info=False,
        called_name=str if code is None else code.called_name,
        code_mode_run_name=None if code is None else code.shape.run_name,
    )


@pytest.mark.parametrize("family", list(ToolFamily))
def test_code_mode_guidance_names_the_shape_s_run_tool(family: ToolFamily) -> None:
    offered = with_code_mode(
        [MemoryTool(tool_id=1, llm=MagicMock())], CODE_MODE_SHAPES[family]
    )[0]
    prompt = _code_mode_prompt(offered)
    for other, shape in CODE_MODE_SHAPES.items():
        assert (CODE_MODE_GUIDANCE.format(name=shape.run_name) in prompt) is (
            other is family
        )


@pytest.mark.parametrize("code_mode", [False, True])
def test_tool_sections_name_a_tool_as_the_model_calls_it(code_mode: bool) -> None:
    memory: list[Tool] = [MemoryTool(tool_id=1, llm=MagicMock())]
    offered = with_code_mode(memory, OPENAI_CODE_MODE)[0] if code_mode else memory
    prompt = _code_mode_prompt(offered)
    name = "tools.add_memory" if code_mode else "add_memory"
    assert MEMORY_GUIDANCE.format(name=name) in prompt


@pytest.mark.parametrize("code_mode", [False, True])
def test_the_sandbox_section_names_the_turn_s_sandbox_tools(code_mode: bool) -> None:
    def prompt(tools: list[Tool]) -> str:
        offered = with_code_mode(tools, OPENAI_CODE_MODE)[0] if code_mode else tools
        return _code_mode_prompt(offered)

    turn = SandboxTurn(
        tenant_id="t",
        user_id=uuid4(),
        chat_session_id=uuid4(),
        vm_chat_files=[],
        copy_vm_chat_files=False,
        shell=SHELL_SHAPES[ToolFamily.OPENAI],
    )
    prefix = "tools." if code_mode else ""
    assert "## Sandbox" not in prompt([EchoTool()])
    assert (
        f"Run commands with `{prefix}exec_command`, use `{prefix}write_stdin` for "
        f"commands that are still running and edit files with `{prefix}apply_patch`."
    ) in prompt(
        [
            ExecCommandTool(turn),
            WriteStdinTool(turn),
            ApplyPatchTool(turn),
        ]
    )
    only_exec = prompt([ExecCommandTool(turn)])
    assert f"Run commands with `{prefix}exec_command`." in only_exec
    assert "apply_patch" not in only_exec
    assert ("Call them from `exec` programs." in only_exec) is code_mode


@pytest.mark.parametrize("include_sandbox", [False, True])
def test_the_token_reservation_counts_code_mode_guidance(
    include_sandbox: bool,
) -> None:
    reserved = build_system_prompt(
        "base",
        include_user_info=False,
        all_guidance_family=ToolFamily.OPENAI,
        all_guidance_sandbox=include_sandbox,
    )
    assert CODE_MODE_GUIDANCE.format(name=EXEC_TOOL_NAME) in reserved
    assert ("## Sandbox" in reserved) is include_sandbox


def _guided(tool_type: type[Tool], name: str) -> MagicMock:
    tool = MagicMock(spec=tool_type)
    tool.name = name
    tool.rank = tool_type.rank
    return tool


def _guidance_headings(prompt: str) -> list[str]:
    """The headings of the tool section, with `search` where the search
    guidance, which has no heading, starts."""
    tools_section = prompt.split(TOOL_SECTION_HEADER, 1)[1].replace(
        TOOL_DESCRIPTION_SEARCH_GUIDANCE, "## search\n"
    )
    return [line[3:] for line in tools_section.splitlines() if line.startswith("## ")]


def test_tool_guidance_follows_the_tool_order_in_both_prompt_variants() -> None:
    turn = SandboxTurn(
        tenant_id="t",
        user_id=uuid4(),
        chat_session_id=uuid4(),
        vm_chat_files=[],
        copy_vm_chat_files=False,
        shell=SHELL_SHAPES[ToolFamily.OPENAI],
    )
    # Offered in another order than the ranks.
    offered: list[Tool] = [
        _guided(PostgresTool, PostgresTool.NAME),
        _guided(ImageGenerationTool, ImageGenerationTool.NAME),
        _guided(PythonTool, PythonTool.NAME),
        _guided(OpenURLTool, OPEN_URL_TOOL_NAME),
        _guided(WebSearchTool, WebSearchTool.NAME),
        WriteStdinTool(turn),
        ApplyPatchTool(turn),
        ExecCommandTool(turn),
        _guided(SearchTool, SearchTool.NAME),
        *with_code_mode([MemoryTool(tool_id=1, llm=MagicMock())], OPENAI_CODE_MODE)[0],
    ]
    expected = [
        "search",
        EXEC_TOOL_NAME,
        SearchTool.NAME,
        "Sandbox",
        WebSearchTool.NAME,
        OPEN_URL_TOOL_NAME,
        PostgresTool.NAME,
        PythonTool.NAME,
        ImageGenerationTool.NAME,
        MemoryTool.NAME,
    ]

    offered_prompt = _code_mode_prompt(offered)
    estimate_prompt = build_system_prompt(
        "base",
        include_user_info=False,
        all_guidance_family=ToolFamily.OPENAI,
        all_guidance_sandbox=True,
    )

    # The memory tool runs inside programs, so the prompt names its function.
    assert _guidance_headings(offered_prompt) == [
        *expected[:-1],
        f"tools.{MemoryTool.NAME}",
    ]
    assert _guidance_headings(estimate_prompt) == expected
    # The sandbox section names its tools in tool order too.
    assert (
        "Run commands with `exec_command`, use `write_stdin` for commands that "
        "are still running and edit files with `apply_patch`."
    ) in offered_prompt


@pytest.mark.parametrize("family", list(ToolFamily))
@pytest.mark.parametrize("code_mode", [False, True])
@pytest.mark.parametrize("with_sandbox", [False, True])
def test_the_search_guidance_opens_the_tools_section(
    family: ToolFamily, code_mode: bool, with_sandbox: bool
) -> None:
    """The search guidance has no heading, so it comes before every tool's
    section and never reads as part of one, also when web search, which
    ranks after the code mode and sandbox tools, is the only search tool."""
    sandbox = SANDBOX_TOOLS[family]
    turn = SandboxTurn(
        tenant_id="t",
        user_id=uuid4(),
        chat_session_id=uuid4(),
        vm_chat_files=[],
        copy_vm_chat_files=False,
        shell=sandbox.shell,
    )
    functions: list[Tool] = [
        MemoryTool(tool_id=1, llm=MagicMock()),
        *([tool(turn) for tool in sandbox.tools] if with_sandbox else []),
    ]
    offered = [
        _guided(WebSearchTool, WebSearchTool.NAME),
        *(
            with_code_mode(functions, CODE_MODE_SHAPES[family])[0]
            if code_mode
            else functions
        ),
    ]
    estimate = build_system_prompt(
        "base",
        include_user_info=False,
        all_guidance_family=family,
        all_guidance_sandbox=with_sandbox,
    )

    for prompt in (_code_mode_prompt(offered), estimate):
        assert prompt.split(TOOL_SECTION_HEADER, 1)[1].startswith(
            TOOL_DESCRIPTION_SEARCH_GUIDANCE
        )


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


def test_function_tools_move_into_the_run_tool() -> None:
    offered, cells = with_code_mode(
        [EchoTool(), _DirectOnlyTool(), _LookupTool()], OPENAI_CODE_MODE
    )
    assert cells is not None
    assert [tool.name for tool in offered] == [
        "send_email",
        EXEC_TOOL_NAME,
        WAIT_TOOL_NAME,
    ]
    code_mode = offered[1]
    assert [tool.name for tool in code_mode.inner_tools] == ["echo", "lookup"]
    assert not offered[2].inner_tools
    assert [tool.id for tool in offered[1:]] == [None, None]


def test_without_function_tools_the_tools_stay_direct() -> None:
    tools: list[Tool] = [_DirectOnlyTool()]
    assert with_code_mode(tools, OPENAI_CODE_MODE) == (tools, None)


def test_a_tool_that_waits_for_child_runs_must_be_direct() -> None:
    with pytest.raises(ValueError, match="send_email"):
        with_code_mode([EchoTool(), _NestedChildRunTool()], OPENAI_CODE_MODE)


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
        (EchoTool().id, "tools.echo (a function in `exec` programs)"),
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
        preferred_tool=CapabilityEntry(tool_id=preferred_tool_id),
    )
    run_agent(agent, messages=[UserMessage(content="Find")], max_steps=3)

    [request] = llm.requests
    assert _offered(request) == [
        EXEC_TOOL_NAME,
        WAIT_TOOL_NAME,
        "send_email",
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
                    name=EXEC_TOOL_NAME, arguments='{"code": "print(1)"}'
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
    )
    run_agent(agent, messages=[UserMessage(content="Find")], max_steps=2)

    first, final = llm.requests
    assert first["tools"] == final["tools"]
    assert _offered(final) == [
        EXEC_TOOL_NAME,
        WAIT_TOOL_NAME,
        "send_email",
    ]
    assert final["tool_choice"] == ToolChoiceOptions.NONE


def test_the_next_run_of_the_same_agent_starts_new_cells() -> None:
    """A message to an idle child starts a new run of the loaded agent."""

    def program(call_id: str, code: str) -> Delta:
        return Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    index=0,
                    id=call_id,
                    function=ResponseFunctionCall(
                        name=EXEC_TOOL_NAME, arguments=json.dumps({"code": code})
                    ),
                )
            ]
        )

    llm = ScriptedLLM(
        [
            program("call-0", 'store("answer", 41)\nprint(42)'),
            Delta(content="One."),
            # The next run reads what the first run stored for this chat.
            program("call-1", 'print(load("answer") + 1)'),
            Delta(content="Two."),
        ]
    )
    agent = ChatAgent(
        messages=[],
        tools=[EchoTool()],
        code_mode=True,
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,
    )
    run_agent(agent, messages=[UserMessage(content="First")], max_steps=3)
    run_agent(agent, messages=[UserMessage(content="Again")], max_steps=3)

    first, second = [
        message
        for message in agent.state.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert "cell 1" in first.content and "42" in first.content
    assert not second.is_error
    assert "cell 2" in second.content and "42" in second.content


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
        all_injected_file_metadata={
            "file-1": FileToolMetadata(
                file_id="file-1", filename="report.pdf", approx_char_count=90_000
            )
        },
    )
    run_agent(agent, messages=[UserMessage(content="Summarize")], max_steps=3)

    [request] = llm.requests
    assert _offered(request) == [
        EXEC_TOOL_NAME,
        WAIT_TOOL_NAME,
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


@pytest.mark.parametrize(
    ("family", "named", "unnamed"),
    [
        (
            ToolFamily.CLAUDE,
            ["`bash`", "`edit`", "`write`", "## repl\n", "## web_fetch\n"],
            ["`apply_patch`", "## exec\n", "## open_url\n"],
        ),
        (
            ToolFamily.OPENAI,
            ["`exec_command`", "`apply_patch`", "## exec\n", "## open_url\n"],
            ["`edit`", "## repl\n", "## web_fetch\n"],
        ),
    ],
)
def test_the_token_estimate_names_the_model_s_tools(
    family: ToolFamily, named: list[str], unnamed: list[str]
) -> None:
    prompts: list[str] = []

    def count(text: str) -> int:
        prompts.append(text)
        return len(text)

    calculate_reserved_tokens(
        db_session=MagicMock(),
        persona_system_prompt="",
        base_system_prompt="base",
        token_counter=count,
        tool_family=family,
        sandbox_tools=True,
    )
    [estimate] = prompts
    assert [name for name in named if name not in estimate] == []
    assert [name for name in unnamed if name in estimate] == []


class _DeferredTool(_LookupTool):
    """A tool whose program function is deferred, so programs can search."""

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DEFERRED


def _sandbox_tools(family: ToolFamily) -> list[Tool]:
    turn = MagicMock(spec=SandboxTurn)
    turn.shell = SHELL_SHAPES[family]
    turn.vm_chat_files = []
    return [ExecCommandTool(turn), WriteStdinTool(turn)]


class _NamedTool(EchoTool):
    """A tool by the name of a tool that has a shape per tool family."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    @property
    def name(self) -> str:
        return self._name


def _not_offered(name: str, use: str) -> str:
    return f"`{name}` is not a tool in this chat. {use}"


@pytest.mark.parametrize(
    ("family", "code_mode", "tools", "called", "expected"),
    [
        # Another shape's code mode tools and program functions.
        (
            ToolFamily.OPENAI,
            True,
            [EchoTool()],
            "repl",
            _not_offered("repl", "Run a program with `exec`."),
        ),
        (
            ToolFamily.OPENAI,
            True,
            [EchoTool()],
            "poll",
            _not_offered("poll", "Wait on a running cell with `wait`."),
        ),
        (
            ToolFamily.CLAUDE,
            True,
            [EchoTool()],
            "exec",
            _not_offered("exec", "Run a program with `repl`."),
        ),
        # The search exists only with deferred functions.
        (
            ToolFamily.OPENAI,
            True,
            [EchoTool()],
            "search_tools",
            "Tool search_tools is unavailable for this step.",
        ),
        (
            ToolFamily.OPENAI,
            True,
            [EchoTool(), _DeferredTool()],
            "search_tools",
            _not_offered(
                "search_tools", "Call `await tool_search(...)` in `exec` programs."
            ),
        ),
        (
            ToolFamily.OPENAI,
            True,
            [EchoTool(), _DeferredTool()],
            "describe_tool",
            _not_offered(
                "describe_tool", "Call `await tool_search(...)` in `exec` programs."
            ),
        ),
        (
            ToolFamily.OPENAI,
            True,
            [EchoTool(), _DeferredTool()],
            "tool_search",
            _not_offered(
                "tool_search", "Call `await tool_search(...)` in `exec` programs."
            ),
        ),
        (
            ToolFamily.CLAUDE,
            True,
            [EchoTool(), _DeferredTool()],
            "tool_search",
            _not_offered(
                "tool_search", "Call `await search_tools(...)` in `repl` programs."
            ),
        ),
        # The Claude shape describes listed functions too.
        (
            ToolFamily.CLAUDE,
            True,
            [EchoTool()],
            "describe_tool",
            _not_offered(
                "describe_tool", "Call `await describe_tool(...)` in `repl` programs."
            ),
        ),
        # Another shape's name of a tool that the agent has.
        (
            ToolFamily.CLAUDE,
            False,
            _sandbox_tools(ToolFamily.CLAUDE),
            "exec_command",
            _not_offered("exec_command", "Call `bash` instead."),
        ),
        (
            ToolFamily.CLAUDE,
            True,
            _sandbox_tools(ToolFamily.CLAUDE),
            "exec_command",
            _not_offered(
                "exec_command",
                "Call `await tools.bash(command=...)` in `repl` programs.",
            ),
        ),
        # A strict schema's optional arguments, which accept null, are not
        # listed as required.
        (
            ToolFamily.CLAUDE,
            True,
            _sandbox_tools(ToolFamily.CLAUDE),
            "bash",
            "`bash` is available only inside `repl` programs. Call it there: "
            "`await tools.bash(command=...)`.",
        ),
        (
            ToolFamily.OPENAI,
            False,
            _sandbox_tools(ToolFamily.OPENAI),
            "bash",
            _not_offered("bash", "Call `exec_command` instead."),
        ),
        *(
            (
                family,
                False,
                [_NamedTool(own)],
                called,
                _not_offered(called, f"Call `{own}` instead."),
            )
            for family, own, called in (
                (ToolFamily.OPENAI, "skills_read", "skill"),
                (ToolFamily.CLAUDE, "skill", "skills_read"),
                (ToolFamily.OPENAI, "open_url", "web_fetch"),
                (ToolFamily.CLAUDE, "web_fetch", "open_url"),
                (ToolFamily.OPENAI, "request_user_input", "ask_user_question"),
                (ToolFamily.CLAUDE, "ask_user_question", "request_user_input"),
            )
        ),
        # A tool that the agent does not have by any name.
        (
            ToolFamily.CLAUDE,
            False,
            [EchoTool()],
            "exec_command",
            "Tool exec_command is unavailable for this step.",
        ),
    ],
)
def test_a_call_by_another_shape_s_name_says_what_to_call(
    family: ToolFamily,
    code_mode: bool,
    tools: list[Tool],
    called: str,
    expected: str,
) -> None:
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        id="call",
                        function=ResponseFunctionCall(name=called, arguments="{}"),
                    )
                ]
            ),
            Delta(content="Done."),
        ],
        family=family,
    )
    agent = ChatAgent(
        messages=[],
        tools=tools,
        code_mode=code_mode,
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,
    )
    run_agent(agent, messages=[UserMessage(content="Go")], max_steps=3)

    [result] = [
        message
        for message in agent.state.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert (result.content, result.is_error) == (expected, True)


@pytest.mark.parametrize(
    ("family", "called", "own"),
    [
        (ToolFamily.OPENAI, "agent", "spawn_agent"),
        (ToolFamily.CLAUDE, "spawn_agent", "agent"),
    ],
)
def test_a_call_of_another_shape_s_spawn_tool_names_the_agent_s_own(
    family: ToolFamily, called: str, own: str
) -> None:
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        id="call",
                        function=ResponseFunctionCall(name=called, arguments="{}"),
                    )
                ]
            ),
            Delta(content="Done."),
        ],
        family=family,
    )
    agent = ChatAgent(
        messages=[],
        tools=[EchoTool()],
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,
        create_subagent=MagicMock(),
    )
    run_agent(agent, messages=[UserMessage(content="Go")], max_steps=3)

    [result] = [
        message
        for message in agent.state.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert result.content == _not_offered(called, f"Call `{own}` instead.")
