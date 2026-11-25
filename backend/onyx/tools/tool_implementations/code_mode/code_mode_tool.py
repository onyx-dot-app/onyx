"""The code mode run and wait tools: model-written Python programs that call
other tools, run as cells of the response (code_mode/cells.py). Each tool
family gets its own shape of them (code_mode/shapes.py)."""

from collections.abc import Callable
from functools import partial

from onyx.agents.tools import (
    NestedInputAnswer,
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
)
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    ToolCallException,
    ToolContext,
    ToolPreference,
)
from onyx.tools.tool_implementations.code_mode.cells import (
    CodeCells,
    Program,
    SequentialCalls,
)
from onyx.tools.tool_implementations.code_mode.models import SandboxLimits
from onyx.tools.tool_implementations.code_mode.prompt import (
    INNER_CALL_MESSAGE,
    OTHER_OPERATION_MESSAGE,
    PROGRAM_FUNCTION_USE,
    RUN_USE,
    WAIT_DESCRIPTION,
    WAIT_USE,
    code_mode_description,
    program_function_operation,
)
from onyx.tools.tool_implementations.code_mode.sandbox import TOOLS_NAMESPACE
from onyx.tools.tool_implementations.code_mode.shapes import (
    CODE_MODE_SHAPES,
    RUN_TOOL_NAMES,
    WAIT_TOOL_NAMES,
    CodeModeShape,
)
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs

RESTORED_RUNNING_MESSAGE = (
    "Execution was interrupted before it finished and was not run again. Its tool "
    "calls are not known: calls it made may have run and had effects. Check before "
    "you retry. Its store writes were discarded."
)
RESTORED_WAIT_MESSAGE = (
    "{wait} was interrupted when the server stopped, and the cell stopped. Its "
    "calls after its last output are not known: they may have run and had effects. "
    "Check before you retry."
)

# The saved result of a run call that stopped before it returned. A program's
# tool calls can have effects, so it never runs twice.
INTERRUPTED_PROGRAM_RESULT = ToolResult(content=RESTORED_RUNNING_MESSAGE, is_error=True)


class CodeModeTool(Tool):
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
        # The cells' shape names this tool and its programs' functions.
        self.shape = cells.shape
        self._inner_tools = list(inner_tools)
        self._cells = cells
        self._limits = limits
        self._stubs = build_tool_stubs(self.shape, self._inner_tools)
        run = self.shape.run_name
        # The program search exists only with deferred functions.
        search = self.shape.search if self._stubs.tool_index is not None else None
        describe = self.shape.describe or search
        # What a call of a code mode operation of any shape, as a tool that
        # this chat does not offer, says to use instead.
        self._operation_uses = {
            **dict.fromkeys(RUN_TOOL_NAMES, RUN_USE.format(run=run)),
            **dict.fromkeys(
                WAIT_TOOL_NAMES, WAIT_USE.format(wait=self.shape.wait_name)
            ),
            **{
                function.name: PROGRAM_FUNCTION_USE.format(function=use.name, run=run)
                for shape in CODE_MODE_SHAPES.values()
                for function, use in (
                    (shape.search, search),
                    (shape.describe, describe),
                )
                if function is not None and use is not None
            },
        }
        # Calls to a sequential tool run one at a time, as they do outside programs.
        sequences: dict[str, SequentialCalls] = {}
        self._sequential_calls = {
            tool.name: sequences.setdefault(
                tool.sequence_group or tool.name, SequentialCalls()
            )
            for tool in self._inner_tools
            if tool.execution_mode == ToolExecutionMode.SEQUENTIAL
        }
        self.resume_with_input = self._resume_with_input
        self.continue_open_input = partial(cells.continue_open, programs=self.program)

    def program(self, code: str, limits: SandboxLimits) -> Program:
        """A program that calls this tool's functions."""
        return Program(
            code=code,
            stubs=self._stubs,
            limits=limits,
            sequential_calls=self._sequential_calls,
        )

    @property
    def inner_tools(self) -> list[Tool]:
        return self._inner_tools

    def operation_names(self, preference: ToolPreference) -> list[str]:
        return [
            program_function_operation(
                function.called_name, self.shape, deferred=function.deferred
            )
            for function in self._stubs.functions.values()
            if function.tool.matches(preference)
        ]

    def called_name(self, tool_name: str) -> str:
        """The name that the model calls the tool named `tool_name` by:
        `tools.<function>` for a function of this tool's programs, else the
        tool's own name."""
        function = next(
            (
                function
                for function in self._stubs.functions.values()
                if function.tool.name == tool_name
            ),
            None,
        )
        return tool_name if function is None else function.called_name

    def inner_call_hint(self, name: str) -> str | None:
        """`name` is a function name, as the description lists it, or the
        name of its tool, also after `tools.` or `tools_`; or the name of a
        code mode tool or program function of any shape."""
        if name in self._operation_uses:
            return OTHER_OPERATION_MESSAGE.format(
                name=name, use=self._operation_uses[name]
            )
        candidates = [
            name,
            name.removeprefix(f"{TOOLS_NAMESPACE}."),
            name.removeprefix(f"{TOOLS_NAMESPACE}_"),
        ]
        function = next(
            (
                function
                for candidate in candidates
                for function in self._stubs.functions.values()
                if candidate in (function.function_name, function.tool.name)
            ),
            None,
        )
        if function is None:
            return None
        return INNER_CALL_MESSAGE.format(
            name=name,
            run=self.shape.run_name,
            called_name=function.called_name,
            arguments=", ".join(
                f"{argument}=..." for argument in sorted(function.required_arguments)
            )
            or "...",
        )

    @property
    def id(self) -> None:
        return None

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT

    @property
    def name(self) -> str:
        return self.shape.run_name

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
        return tool_definition_from_arguments(
            self.name,
            code_mode_description(self._stubs, self._limits),
            self.shape.run_arguments,
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        request = parse_tool_arguments(
            self.shape.run_arguments, invocation.arguments
        ).request()
        if not request.code.strip():
            raise ToolCallException(
                message=f"{self.shape.run_name} received an empty program",
                llm_facing_message="The `code` argument is empty. Provide a Python program.",
            )
        return self._cells.start(
            self.program(request.code, self._limits),
            invocation,
            context,
            yield_seconds=request.yield_seconds,
            max_chars=request.max_chars,
        )

    def _resume_with_input(
        self,
        invocation: ToolInvocation,
        context: ToolContext,
        answers: list[NestedInputAnswer],
    ) -> ToolOutcome:
        request = parse_tool_arguments(
            self.shape.run_arguments, invocation.arguments
        ).request()
        return self._cells.resume(
            invocation,
            context,
            answers,
            programs=self.program,
            yield_seconds=request.yield_seconds,
        )


class WaitCodeTool(Tool):
    DISPLAY_NAME = "Code"
    DESCRIPTION = "Wait for a running code cell."

    def __init__(
        self, cells: CodeCells, programs: Callable[[str, SandboxLimits], Program]
    ) -> None:
        self.shape = cells.shape
        # The saved result of a call that stopped before it returned. The
        # cell's last saved observation keeps reporting it running, so the
        # run's finish adds the closing record there.
        self.interrupted_result = ToolResult(
            content=RESTORED_WAIT_MESSAGE.format(wait=self.shape.wait_name),
            is_error=True,
        )
        self._cells = cells
        # Builds a saved cell's program with the current tools.
        self._programs = programs
        self.resume_with_input = self._resume_with_input
        self.continue_open_input = partial(cells.continue_open, programs=programs)

    @property
    def id(self) -> None:
        return None

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT

    @property
    def name(self) -> str:
        return self.shape.wait_name

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
        return tool_definition_from_arguments(
            self.name,
            WAIT_DESCRIPTION.format(run=self.shape.run_name, wait=self.shape.wait_name),
            self.shape.wait_arguments,
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        request = parse_tool_arguments(
            self.shape.wait_arguments, invocation.arguments
        ).request()
        return self._cells.wait(
            request.cell_id,
            invocation,
            context,
            programs=self._programs,
            yield_seconds=request.yield_seconds,
            max_chars=request.max_chars,
            terminate=request.terminate,
        )

    def _resume_with_input(
        self,
        invocation: ToolInvocation,
        context: ToolContext,
        answers: list[NestedInputAnswer],
    ) -> ToolOutcome:
        request = parse_tool_arguments(
            self.shape.wait_arguments, invocation.arguments
        ).request()
        return self._cells.resume(
            invocation,
            context,
            answers,
            programs=self._programs,
            yield_seconds=request.yield_seconds,
        )


def with_code_mode(
    tools: list[Tool], shape: CodeModeShape
) -> tuple[list[Tool], CodeCells | None]:
    """Offer each tool as its `code_mode_exposure` declares: DIRECT tools stay
    direct, the others become Python functions inside programs of the shape's
    run tool.

    The run and wait tools share the returned cells of each run; None when no
    tool is a function. Raises ValueError for a tool that waits for child runs
    but is not DIRECT, since a program cannot wait for them.
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
    cells = CodeCells(shape)
    code_tool = CodeModeTool(inner, cells=cells, limits=SandboxLimits())
    return [
        *(tool for tool in tools if tool.code_mode_exposure is CodeModeExposure.DIRECT),
        code_tool,
        WaitCodeTool(cells, code_tool.program),
    ], cells
