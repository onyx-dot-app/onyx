"""The shapes of the code mode operations: run a program, wait on its cell,
search the deferred functions, and describe one function. Each tool family
names them and takes their arguments its own way; each shape's arguments
normalize into the same requests, which the cells serve (code_mode/cells.py)."""

from collections.abc import Callable, Mapping
from typing import ClassVar, NamedTuple

from pydantic import Field

from onyx.llm.model_capabilities import ToolFamily
from onyx.tools.constants import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    EXEC_TOOL_NAME,
    MAX_OUTPUT_TOKENS_DESCRIPTION,
    POLL_TOOL_NAME,
    REPL_TOOL_NAME,
    WAIT_TOOL_NAME,
)
from onyx.tools.interface import ToolArguments
from onyx.tools.tool_implementations.code_mode.sandbox import TOOLS_NAMESPACE
from onyx.tools.tool_implementations.code_mode.tool_search import (
    DEFAULT_TOOL_SEARCH_LIMIT,
    MAX_TOOL_SEARCH_LIMIT,
    TOOL_MATCH_TYPE,
    ToolIndex,
)
from onyx.tools.tool_implementations.utils import output_chars_from_tokens

# How long a call waits for the cell before it returns the output so far.
DEFAULT_EXECUTE_YIELD_MS = 30_000
MAX_EXECUTE_YIELD_MS = 120_000
DEFAULT_WAIT_YIELD_MS = 15_000
MAX_WAIT_YIELD_MS = 300_000
MIN_YIELD_MS = 1_000


def yield_seconds(yield_time_ms: int, maximum_ms: int) -> float:
    return min(max(yield_time_ms, MIN_YIELD_MS), maximum_ms) / 1000


class RunRequest(NamedTuple):
    """A call of the run operation: start a program as a new cell."""

    code: str
    yield_seconds: float
    max_chars: int


class WaitRequest(NamedTuple):
    """A call of the wait operation: observe a cell, or stop it."""

    cell_id: int
    yield_seconds: float
    max_chars: int
    terminate: bool


class ExecArguments(ToolArguments[RunRequest]):
    # The argument that bounds how long a call waits for the program.
    YIELD_ARGUMENT: ClassVar[str] = "yield_time_ms"

    code: str = Field(description="The Python program to run.")
    yield_time_ms: int = Field(
        default=DEFAULT_EXECUTE_YIELD_MS,
        description="How long to wait for the program before returning its output "
        f"so far while it keeps running. Defaults to {DEFAULT_EXECUTE_YIELD_MS} ms, "
        f"at most {MAX_EXECUTE_YIELD_MS} ms.",
    )
    max_output_tokens: int = Field(
        default=DEFAULT_MAX_OUTPUT_TOKENS, description=MAX_OUTPUT_TOKENS_DESCRIPTION
    )

    def request(self) -> RunRequest:
        return RunRequest(
            code=self.code,
            yield_seconds=yield_seconds(self.yield_time_ms, MAX_EXECUTE_YIELD_MS),
            max_chars=output_chars_from_tokens(self.max_output_tokens),
        )


class ReplArguments(ToolArguments[RunRequest]):
    # The argument that bounds how long a call waits for the program.
    YIELD_ARGUMENT: ClassVar[str] = "timeout"

    code: str = Field(description="The Python program to run.")
    timeout: int = Field(
        default=DEFAULT_EXECUTE_YIELD_MS,
        description="Milliseconds to wait for the program before returning its "
        "output so far while it keeps running. Defaults to "
        f"{DEFAULT_EXECUTE_YIELD_MS}, at most {MAX_EXECUTE_YIELD_MS}.",
    )

    def request(self) -> RunRequest:
        return RunRequest(
            code=self.code,
            yield_seconds=yield_seconds(self.timeout, MAX_EXECUTE_YIELD_MS),
            max_chars=output_chars_from_tokens(DEFAULT_MAX_OUTPUT_TOKENS),
        )


class WaitArguments(ToolArguments[WaitRequest]):
    cell_id: int = Field(description="Identifier of the running cell.")
    yield_time_ms: int = Field(
        default=DEFAULT_WAIT_YIELD_MS,
        description="How long to wait for more output before returning. Defaults "
        f"to {DEFAULT_WAIT_YIELD_MS} ms, at most {MAX_WAIT_YIELD_MS} ms.",
    )
    max_tokens: int = Field(
        default=DEFAULT_MAX_OUTPUT_TOKENS, description=MAX_OUTPUT_TOKENS_DESCRIPTION
    )
    terminate: bool = Field(
        default=False,
        description="True stops the running cell; false or omitted waits for output.",
    )

    def request(self) -> WaitRequest:
        return WaitRequest(
            cell_id=self.cell_id,
            yield_seconds=yield_seconds(self.yield_time_ms, MAX_WAIT_YIELD_MS),
            max_chars=output_chars_from_tokens(self.max_tokens),
            terminate=self.terminate,
        )


class PollArguments(ToolArguments[WaitRequest]):
    cell_id: int = Field(description="Identifier of the running cell.")
    timeout: int = Field(
        default=DEFAULT_WAIT_YIELD_MS,
        description="Milliseconds to wait for more output before returning. "
        f"Defaults to {DEFAULT_WAIT_YIELD_MS}, at most {MAX_WAIT_YIELD_MS}.",
    )
    terminate: bool = Field(
        default=False,
        description="True stops the running cell; false or omitted waits for output.",
    )

    def request(self) -> WaitRequest:
        return WaitRequest(
            cell_id=self.cell_id,
            yield_seconds=yield_seconds(self.timeout, MAX_WAIT_YIELD_MS),
            max_chars=output_chars_from_tokens(DEFAULT_MAX_OUTPUT_TOKENS),
            terminate=self.terminate,
        )


class ProgramFunction(NamedTuple):
    """A host function that programs await, as its stub declares it."""

    name: str
    # The stub after `async def <name>`: the signature and the docstring.
    signature: str

    @property
    def stub(self) -> str:
        return f"async def {self.name}{self.signature}"


def _search_signature(limit: str) -> str:
    return f'''(query: str, {limit}: int = {DEFAULT_TOOL_SEARCH_LIMIT}) -> list[{TOOL_MATCH_TYPE}]:
    """Find tool functions that this description does not list, best match first.

    Each match has the function name, its description, and its full stub with
    the argument and result types. Call a match as `await {TOOLS_NAMESPACE}.<name>(...)`.
    At most `{limit}` matches, up to {MAX_TOOL_SEARCH_LIMIT}.
    """
    ...'''


# The search host function of each shape; its argument names are the stub's.
def _tool_search(
    index: ToolIndex, query: object, limit: object = DEFAULT_TOOL_SEARCH_LIMIT
) -> list[dict[str, str]]:
    return index.matches(query, limit, "limit")


def _search_tools(
    index: ToolIndex,
    query: object,
    max: object = DEFAULT_TOOL_SEARCH_LIMIT,  # noqa: A002
) -> list[dict[str, str]]:
    return index.matches(query, max, "max")


class CodeModeShape(NamedTuple):
    """How one tool family names and calls the code mode operations."""

    run_name: str
    wait_name: str
    run_arguments: type[ToolArguments[RunRequest]]
    # The run argument that bounds how long a call waits for the program.
    run_yield_argument: str
    wait_arguments: type[ToolArguments[WaitRequest]]
    # The program function that searches the deferred functions, and its host
    # function.
    search: ProgramFunction
    search_host: Callable[[ToolIndex, object, object], list[dict[str, str]]]
    # The program function that describes one function by name, when the
    # shape has one.
    describe: ProgramFunction | None


OPENAI_CODE_MODE = CodeModeShape(
    run_name=EXEC_TOOL_NAME,
    wait_name=WAIT_TOOL_NAME,
    run_arguments=ExecArguments,
    run_yield_argument=ExecArguments.YIELD_ARGUMENT,
    wait_arguments=WaitArguments,
    search=ProgramFunction("tool_search", _search_signature("limit")),
    search_host=_tool_search,
    describe=None,
)
# The shape Claude models are trained on.
CLAUDE_CODE_MODE = CodeModeShape(
    run_name=REPL_TOOL_NAME,
    wait_name=POLL_TOOL_NAME,
    run_arguments=ReplArguments,
    run_yield_argument=ReplArguments.YIELD_ARGUMENT,
    wait_arguments=PollArguments,
    search=ProgramFunction("search_tools", _search_signature("max")),
    search_host=_search_tools,
    describe=ProgramFunction(
        "describe_tool",
        f'''(name: str) -> {TOOL_MATCH_TYPE}:
    """The name, description and full stub of one tool function, listed or
    not. Raises ValueError when no function has the name.
    """
    ...''',
    ),
)
CODE_MODE_SHAPES: Mapping[ToolFamily, CodeModeShape] = {
    ToolFamily.OPENAI: OPENAI_CODE_MODE,
    ToolFamily.CLAUDE: CLAUDE_CODE_MODE,
}

# The names of each operation across the shapes: a chat's history can hold
# calls of every shape.
RUN_TOOL_NAMES = frozenset(shape.run_name for shape in CODE_MODE_SHAPES.values())
WAIT_TOOL_NAMES = frozenset(shape.wait_name for shape in CODE_MODE_SHAPES.values())
CODE_MODE_TOOL_NAMES = RUN_TOOL_NAMES | WAIT_TOOL_NAMES
# Globals that the search and describe functions give programs.
PROGRAM_SEARCH_NAMES = frozenset(
    {
        TOOL_MATCH_TYPE,
        *(
            function.name
            for shape in CODE_MODE_SHAPES.values()
            for function in (shape.search, shape.describe)
            if function is not None
        ),
    }
)
