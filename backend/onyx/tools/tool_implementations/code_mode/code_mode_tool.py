"""The execute_code and wait_code tools: model-written Python programs that call
other tools, run as cells of the response (code_mode/cells.py)."""

from pydantic import BaseModel

from onyx.agents.tools import ToolExecutionMode, ToolInvocation
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.constants import CODE_MODE_TOOL_NAME, WAIT_CODE_TOOL_NAME
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import CodeModeExposure, ToolCallException, ToolContext
from onyx.tools.tool_implementations.code_mode.cells import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    CodeCells,
    Program,
    SequentialCalls,
)
from onyx.tools.tool_implementations.code_mode.models import (
    SandboxLimits,
)
from onyx.tools.tool_implementations.code_mode.prompt import (
    WAIT_CODE_DESCRIPTION,
    code_mode_description,
    program_function_operation,
)
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs

# How long a call waits for the cell before it returns the output so far.
DEFAULT_EXECUTE_YIELD_MS = 30_000
MAX_EXECUTE_YIELD_MS = 120_000
DEFAULT_WAIT_YIELD_MS = 15_000
MAX_WAIT_YIELD_MS = 300_000
MIN_YIELD_MS = 1_000
# Tokens of output that one observation can return to the model.
MAX_OUTPUT_TOKENS = 40_000

RESTORED_RUNNING_MESSAGE = (
    "Execution was interrupted before it finished and was not run again. Its tool "
    "calls are not known: calls it made may have run and had effects. Check before "
    "you retry. Its store writes were discarded."
)
RESTORED_WAIT_MESSAGE = (
    "wait_code was interrupted when the server stopped, and the cell stopped. Its "
    "calls after its last output are not known: they may have run and had effects. "
    "Check before you retry."
)


class CodeModeArguments(BaseModel):
    code: str
    yield_time_ms: int = DEFAULT_EXECUTE_YIELD_MS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS


class WaitCodeArguments(BaseModel):
    cell_id: int
    yield_time_ms: int = DEFAULT_WAIT_YIELD_MS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    terminate: bool = False


def yield_seconds(yield_time_ms: int, maximum_ms: int) -> float:
    return min(max(yield_time_ms, MIN_YIELD_MS), maximum_ms) / 1000


def output_tokens(requested: int) -> int:
    return min(max(requested, 1), MAX_OUTPUT_TOKENS)


_MAX_TOKENS_TEXT = (
    f"Defaults to {DEFAULT_MAX_OUTPUT_TOKENS} tokens, at most {MAX_OUTPUT_TOKENS}."
)


# The saved result of an `execute_code` call that stopped before it returned. A
# program's tool calls can have effects, so it never runs twice.
INTERRUPTED_PROGRAM_RESULT = ToolResult(content=RESTORED_RUNNING_MESSAGE, is_error=True)
# The saved result of a `wait_code` call that stopped before it returned. The
# cell's last saved observation keeps reporting it running, so the run's finish
# adds the closing record there.
INTERRUPTED_WAIT_RESULT = ToolResult(content=RESTORED_WAIT_MESSAGE, is_error=True)


class CodeModeTool(Tool):
    NAME = CODE_MODE_TOOL_NAME
    DISPLAY_NAME = "Code"
    DESCRIPTION = "Run a Python program that calls tools."
    interrupted_result = INTERRUPTED_PROGRAM_RESULT

    def __init__(
        self,
        inner_tools: list[Tool],
        *,
        cells: CodeCells,
        limits: SandboxLimits,
    ) -> None:
        self._inner_tools = list(inner_tools)
        self._cells = cells
        self._limits = limits
        self._stubs = build_tool_stubs(self._inner_tools)
        # Calls to a sequential tool run one at a time, as they do outside programs.
        self._sequential_calls = {
            tool.name: SequentialCalls()
            for tool in self._inner_tools
            if tool.execution_mode == ToolExecutionMode.SEQUENTIAL
        }

    @property
    def inner_tools(self) -> list[Tool]:
        return self._inner_tools

    def operation_names(self, tool_id: int) -> list[str]:
        return [
            program_function_operation(name, deferred=function.deferred)
            for name, function in self._stubs.functions.items()
            if function.tool.id == tool_id
        ]

    @property
    def id(self) -> None:
        return None

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=code_mode_description(self._stubs, self._limits),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python program to run.",
                    },
                    "yield_time_ms": {
                        "type": "integer",
                        "description": "How long to wait for the program before "
                        "returning its output so far while it keeps running. "
                        f"Defaults to {DEFAULT_EXECUTE_YIELD_MS} ms, at most "
                        f"{MAX_EXECUTE_YIELD_MS} ms.",
                    },
                    "max_output_tokens": {
                        "type": "integer",
                        "description": "Token budget for the output this call "
                        "returns; longer output is cut in the middle. "
                        + _MAX_TOKENS_TEXT,
                    },
                },
                "required": ["code"],
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        arguments = parse_tool_arguments(CodeModeArguments, invocation.arguments)
        if not arguments.code.strip():
            raise ToolCallException(
                message="execute_code received an empty program",
                llm_facing_message="The `code` argument is empty. Provide a Python program.",
            )
        return self._cells.start(
            Program(
                code=arguments.code,
                stubs=self._stubs,
                limits=self._limits,
                sequential_calls=self._sequential_calls,
            ),
            invocation,
            context,
            yield_seconds=yield_seconds(arguments.yield_time_ms, MAX_EXECUTE_YIELD_MS),
            max_tokens=output_tokens(arguments.max_output_tokens),
        )


class WaitCodeTool(Tool):
    NAME = WAIT_CODE_TOOL_NAME
    DISPLAY_NAME = "Code"
    DESCRIPTION = "Wait for a running code cell."
    interrupted_result = INTERRUPTED_WAIT_RESULT

    def __init__(self, cells: CodeCells) -> None:
        self._cells = cells

    @property
    def id(self) -> None:
        return None

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=WAIT_CODE_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "cell_id": {
                        "type": "integer",
                        "description": "Identifier of the running cell.",
                    },
                    "yield_time_ms": {
                        "type": "integer",
                        "description": "How long to wait for more output before "
                        f"returning. Defaults to {DEFAULT_WAIT_YIELD_MS} ms, at most "
                        f"{MAX_WAIT_YIELD_MS} ms.",
                    },
                    "max_output_tokens": {
                        "type": "integer",
                        "description": "Token budget for the output this call "
                        "returns; longer output is cut in the middle. "
                        + _MAX_TOKENS_TEXT,
                    },
                    "terminate": {
                        "type": "boolean",
                        "description": "True stops the running cell; false or "
                        "omitted waits for output.",
                    },
                },
                "required": ["cell_id"],
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        arguments = parse_tool_arguments(WaitCodeArguments, invocation.arguments)
        return self._cells.wait(
            arguments.cell_id,
            invocation,
            context,
            yield_seconds=yield_seconds(arguments.yield_time_ms, MAX_WAIT_YIELD_MS),
            max_tokens=output_tokens(arguments.max_output_tokens),
            terminate=arguments.terminate,
        )


def with_code_mode(tools: list[Tool]) -> tuple[list[Tool], CodeCells | None]:
    """Offer each tool as its `code_mode_exposure` declares: DIRECT tools stay
    direct, the others become Python functions inside `execute_code`.

    `execute_code` and `wait_code` share the returned cells of one response; None
    when no tool is a function. Raises ValueError for a tool that waits for child
    runs but is not DIRECT, since a program cannot wait for them.
    """
    for tool in tools:
        if (
            tool.result_from_children is not None
            and tool.code_mode_exposure is not CodeModeExposure.DIRECT
        ):
            raise ValueError(
                f"{tool.name} waits for child runs, so its code mode exposure must "
                "be DIRECT."
            )
    inner = [
        tool for tool in tools if tool.code_mode_exposure is not CodeModeExposure.DIRECT
    ]
    if not inner:
        return tools, None
    cells = CodeCells()
    return [
        *(tool for tool in tools if tool.code_mode_exposure is CodeModeExposure.DIRECT),
        CodeModeTool(inner, cells=cells, limits=SandboxLimits()),
        WaitCodeTool(cells),
    ], cells
