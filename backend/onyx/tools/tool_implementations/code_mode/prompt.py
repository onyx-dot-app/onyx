"""Text that the model reads for code mode: tool descriptions and each result."""

import json
import re
from collections.abc import Sequence
from typing import NamedTuple

from onyx.tools.tool_implementations.code_mode.models import (
    CellClosing,
    CellWindow,
    CodeModeCall,
    CodeModeExecutionResult,
    CodeModeStatus,
    DiscardedWrites,
    ExternalCall,
    LostStoreWrites,
    SandboxLimits,
    SandboxResult,
)
from onyx.tools.tool_implementations.code_mode.sandbox import (
    IMPORTABLE_MODULES,
    TOOLS_NAMESPACE,
)
from onyx.tools.tool_implementations.code_mode.shapes import CodeModeShape
from onyx.tools.tool_implementations.code_mode.store import (
    JSON_TYPES_TEXT,
    MAX_STORE_BYTES,
    MAX_STORED_VALUE_BYTES,
    store_summary,
)
from onyx.tools.tool_implementations.code_mode.stubs import ToolStubs
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
    ImageResult,
)
from onyx.tools.tool_implementations.utils import (
    truncate_output,
    truncation_marker,
)

# Characters of the notes after the output; they are never cut by the budget.
MAX_NOTES_CHARS = 10_000
# Bounds on the deferred namespace lines of the run tool's description.
MAX_DEFERRED_NAMESPACES_BYTES = 4 * 1024
MAX_NAMESPACE_DESCRIPTION_CHARS = 250
# Bytes kept for the omitted-namespaces line when the names do not all fit.
_OMITTED_LINE_RESERVE_BYTES = 64
_CUT_SUFFIX = "..."
# The characters that `str.splitlines` breaks lines at.
_LINE_BREAK = re.compile(r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
_DEFERRED_NAMESPACES_HEADING = (
    "\n  Deferred tool namespaces (`{search}` with a namespace finds its "
    "functions; call each by the name in its stub):\n"
)
_UNGROUPED_NOTE = "\n  Other deferred functions are in no namespace."


def _limits_text(limits: SandboxLimits) -> str:
    return (
        f"{limits.max_cpu_seconds:g} seconds of computation, "
        f"{limits.max_tool_calls} tool calls, and "
        f"{limits.max_memory_bytes // (1024 * 1024)} MB of memory"
    )


def _deferred_note(stubs: ToolStubs) -> str:
    """One line per deferred namespace, in `deferred_namespaces` order: its
    name and the first line of its description. The lines fit a byte budget;
    names take it before descriptions."""
    search = stubs.shape.search.name
    heading = _DEFERRED_NAMESPACES_HEADING.format(search=search)
    descriptions = stubs.deferred_namespaces
    ungrouped = (
        _UNGROUPED_NOTE if stubs.has_deferred_functions_without_namespace else ""
    )
    budget = MAX_DEFERRED_NAMESPACES_BYTES - len(f"{heading}{ungrouped}".encode())
    name_bytes = {
        namespace: len(f"  - {namespace}\n".encode()) for namespace in descriptions
    }
    remaining = budget - sum(name_bytes.values())
    lines: list[str] = []
    if remaining < 0:
        remaining = budget - _OMITTED_LINE_RESERVE_BYTES
        for namespace, size in name_bytes.items():
            if size > remaining:
                break
            remaining -= size
            lines.append(f"  - {namespace}")
        omitted = len(name_bytes) - len(lines)
        lines.append(
            f"  ... {omitted} additional namespace{'' if omitted == 1 else 's'} "
            "omitted."
        )
    else:
        # Descriptions take the rest in namespace order, so built-in
        # namespaces keep theirs before integrations do.
        for namespace, description in descriptions.items():
            # The description bytes that fit after ": ".
            cap = remaining - 2
            first_line = _LINE_BREAK.split((description or "").strip(), 1)[0].rstrip()
            if cap <= len(_CUT_SUFFIX) or not first_line:
                lines.append(f"  - {namespace}")
                continue
            if len(first_line) > MAX_NAMESPACE_DESCRIPTION_CHARS:
                first_line = (
                    first_line[: MAX_NAMESPACE_DESCRIPTION_CHARS - len(_CUT_SUFFIX)]
                    + _CUT_SUFFIX
                )
            encoded = first_line.encode()
            if len(encoded) <= cap:
                remaining -= len(encoded) + 2
            else:
                first_line = (
                    encoded[: cap - len(_CUT_SUFFIX)].decode(errors="ignore")
                    + _CUT_SUFFIX
                )
                remaining = 0
            lines.append(f"  - {namespace}: {first_line}")
    listed = f"{heading}{'\n'.join(lines)}{ungrouped}" if lines else ""
    return (
        "\n- More functions are available than the ones in the Functions list "
        f"below. Find them with `await {search}(query)`; each match has the "
        "function's name, description and stub. Read the stub before you call a "
        "function, then call it like a listed one, as "
        f"`await {TOOLS_NAMESPACE}.<name>(...)`, in this program or a later one."
        f"{listed}"
    )


def code_mode_description(stubs: ToolStubs, limits: SandboxLimits) -> str:
    """Model-facing description; deterministic for a given set of tools, shape
    and limits."""
    shape = stubs.shape
    run = shape.run_name
    deferred_note = _deferred_note(stubs) if stubs.tool_index is not None else ""
    describe_note = (
        ""
        if shape.describe is None
        else f"\n- `await {shape.describe.name}(name)` returns the name, description "
        "and full stub of one function."
    )
    return f"""Run a Python program that calls the tools listed below, as in `result = await {TOOLS_NAMESPACE}.tool_name(argument=value)`. Each `{run}` call starts a fresh Python interpreter: variables, functions and imports from earlier calls are gone. Keep values across calls with `store(key, value)` and `load(key)`. Use `{run}` to combine tool calls in one step, run independent calls in parallel, and filter large results before you read them.

- The program runs in Monty, a sandboxed Python interpreter, not CPython. The program is for calling and combining the tools below. It has no files, processes or network of its own; anything outside the program comes from a tool.
- Each tool is an async Python function of the `{TOOLS_NAMESPACE}` namespace, which every program has. Call it as `{TOOLS_NAMESPACE}.<name>` with keyword arguments only and `await` the result. These functions exist only inside programs: you cannot call them as tools yourself. Top-level `await` works; do not call `asyncio.run()`.
- Await every call; calls that are not awaited are cancelled when the program ends.
- Run independent calls in parallel with `asyncio.gather`, for example `a, b = await asyncio.gather({TOOLS_NAMESPACE}.f(x=1), {TOOLS_NAMESPACE}.g(y=2))`. Make a call that needs an earlier result after that result is available.
- `asyncio.gather` takes no keyword arguments, so `return_exceptions=True` is not available, and one failed call fails the whole gather. To keep the other results, wrap each call:
  `async def attempt(call):`
  `    try: return await call`
  `    except Exception as e: return {{"error": str(e)}}`
  `results = await asyncio.gather(*(attempt({TOOLS_NAMESPACE}.f(x=v)) for v in values))`
- Only text that the program prints and the value of the last expression come back to you; that value must be JSON data ({JSON_TYPES_TEXT}). Tool results stay inside the program until you print them. Print only the fields you need, such as titles, document numbers, URLs, and short excerpts. Do not print whole results.
- A tool error raises an exception in the program. To continue after an error, use `try:` / `except Exception as e:`. An uncaught exception stops the program and returns its traceback with the output printed before it.
- Stored values stay available in all later `{run}` calls of this chat, also in later messages. Store only JSON values ({JSON_TYPES_TEXT}). Storing None deletes the key, and `load` returns None for a missing key. `store`, `load` and `yield_control` are plain functions: do not `await` them. A program saves its writes when it ends by itself: it completes, or stops at an uncaught exception. Later programs see them from then on. The writes of a program that is terminated or times out are discarded. Each value can be up to {MAX_STORED_VALUE_BYTES // 1024} KB as JSON, and the whole store up to {MAX_STORE_BYTES // (1024 * 1024)} MB. Store values that you plan to reuse, such as IDs, totals, or filtered results, instead of calling the tools again.
- Each program is limited to {_limits_text(limits)}.
- A program that runs longer than `{shape.run_yield_argument}`, or that calls `yield_control()`, returns its output so far and keeps running as cell N. Call `{shape.wait_name}` with the cell id to get more output or to stop the cell. Do other work while a cell runs. Open cells stop when you give your final answer, so wait for each cell whose result you need first. A cell stops after {limits.lifetime_seconds / 60:g} minutes.
- Supported Python: functions, closures, lambdas, comprehensions, f-strings, `try`/`except`/`finally`, `match`, `@dataclass`, and classes without base classes. Not supported: class inheritance, custom exception classes (catch `Exception`), generators (`yield`), `del`, and `async with`.
- These modules are already imported in every program: {", ".join(IMPORTABLE_MODULES)}. Other modules are not available.
- The program is type-checked before it runs. A wrong argument name or type in a tool call stops the program before any tool runs.
- Search results have a `document` number. To cite a result in your answer, print its `document` number and write [n] in the answer, where n is that number.{describe_note}{deferred_note}

Functions (already defined in every program, no import needed; call the tool functions as `await {TOOLS_NAMESPACE}.<name>(...)`):
```python
{stubs.listed_text.rstrip()}
```"""


# The wait tool's description; `{run}` and `{wait}` are the shape's names.
WAIT_DESCRIPTION = """Waits on a running `{run}` cell and returns new output or completion.
- Use `{wait}` only after `{run}` returns `Execution running in cell N`.
- `{wait}` returns only the new output since the last result for that cell, or the final completion or termination result.
- If the cell is still running, `{wait}` may return again with the same `cell_id`.
- If the cell has already finished, `{wait}` returns the completed result and closes the cell."""


# The result of a call of a tool of another tool family's shapes, by a name
# that this chat does not offer; `{use}` is one of the *_USE texts.
OTHER_OPERATION_MESSAGE = "`{name}` is not a tool in this chat. {use}"
TOOL_USE = "Call `{name}` instead."
RUN_USE = "Run a program with `{run}`."
WAIT_USE = "Wait on a running cell with `{wait}`."
PROGRAM_FUNCTION_USE = "Call `await {function}({arguments})` in `{run}` programs."

# The result of a call of a code mode function as a tool of its own.
INNER_CALL_MESSAGE = (
    "`{name}` is available only inside `{run}` programs. Call it there: "
    "`await {called_name}({arguments})`."
)


def program_function_operation(
    called_name: str, shape: CodeModeShape, *, deferred: bool
) -> str:
    """How a tool preference names a function of the shape's programs."""
    found = (
        f"; find its stub with `await {shape.search.name}(query)`" if deferred else ""
    )
    return f"{called_name} (a function in `{shape.run_name}` programs{found})"


# How each status reads in a sentence about the cell.
_STATUS_TEXT: dict[CodeModeStatus, str] = {
    "running": "running",
    "completed": "completed",
    "failed": "failed",
    "timed_out": "timed out",
    "terminated": "terminated",
    "cancelled": "was cancelled",
}
# Statuses of a program that ended by itself.
_ENDED: frozenset[CodeModeStatus] = frozenset({"completed", "failed", "timed_out"})


def calls_note(calls: Sequence[CodeModeCall]) -> str | None:
    """Each call of a program that did not complete, so the model knows what ran.

    `calls` are in index order.
    """
    if not calls:
        return None
    return (
        "Tool calls:\n"
        + "\n".join(
            f"[{call.index}] {call.function_name}: {call.state}" for call in calls
        )
        + "\nAll of these calls may have had effects, also unfinished calls. Check "
        "before you retry."
    )


def images_note(calls: Sequence[CodeModeCall]) -> str | None:
    """The file id and prompt of each image that `calls` generated, so a later
    message can edit an image that the program did not print."""
    images = [
        ImageResult(
            file_id=image.file_id, revised_prompt=image.revised_prompt
        ).model_dump()
        for call in calls
        if isinstance(call.details, FinalImageGenerationResponse)
        for image in call.details.generated_images
    ]
    return f"Generated images: {json.dumps(images)}" if images else None


def _call_names(calls: Sequence[ExternalCall]) -> list[str]:
    return [f"{call.function_name}[{call.index}]" for call in calls]


def _unstarted_note(calls: Sequence[str]) -> str | None:
    if not calls:
        return None
    names = ", ".join(calls)
    if len(calls) == 1:
        return f"1 tool call was never awaited and never started: {names}."
    return f"{len(calls)} tool calls were never awaited and never started: {names}."


def _unawaited_note(calls: Sequence[str]) -> str | None:
    if not calls:
        return None
    names = ", ".join(calls)
    if len(calls) == 1:
        return (
            f"1 tool call was started but never awaited: {names}. Its cancellation "
            "was requested; it may have had effects. Check before you retry."
        )
    return (
        f"{len(calls)} tool calls were started but never awaited: {names}. "
        "Their cancellation was requested; they may have had effects. Check before "
        "you retry."
    )


def observation_heading(details: CodeModeExecutionResult) -> str:
    seconds = f"{details.duration_seconds:.1f}s"
    count = details.tool_call_count
    calls = f"{count} tool call{'' if count == 1 else 's'}"
    status = details.status
    timing = f"in {seconds}" if status in _ENDED else f"after {seconds}"
    so_far = " so far" if status == "running" else ""
    return (
        f"Execution {_STATUS_TEXT[status]} in cell {details.cell_id} {timing} "
        f"with {calls}{so_far}."
    )


def closing_heading(cell_id: int, closing: CellClosing) -> str:
    """How a cell's closing record starts: what happened after the observation
    that it amends."""
    if closing.reason == "interrupted":
        return (
            f"Cell {cell_id} was interrupted when the server stopped. Calls after "
            "this output are not known; they may have run."
        )
    event = "the run paused" if closing.reason == "suspended" else "the response ended"
    if closing.status in _ENDED:
        return (
            f"Cell {cell_id} {_STATUS_TEXT[closing.status]} after this output, "
            f"before {event}."
        )
    return f"Cell {cell_id} stopped when {event}."


def closed_cell_text(
    cell_id: int, closing: CellClosing | None, *, returned_end: bool, run_name: str
) -> str:
    """What the wait tool returns for a closed cell: how the cell's saved
    results report its end. `closing` is the cell's closing record;
    `returned_end` says that an observation reported the end."""
    if closing is not None and closing.reason == "interrupted":
        return (
            f"Cell {cell_id} was interrupted when the server stopped. Start a new "
            f"{run_name} call."
        )
    if closing is not None:
        event = (
            "the run paused" if closing.reason == "suspended" else "the response ended"
        )
        if closing.status in _ENDED:
            return (
                f"Cell {cell_id} {_STATUS_TEXT[closing.status]} before {event}; its "
                "output and result are in its earlier result."
            )
        return f"Cell {cell_id} stopped when {event}. Start a new {run_name} call."
    if returned_end:
        return f"Cell {cell_id} already returned its final result."
    return (
        f"Cell {cell_id} stopped when its response ended or its run paused. Start "
        f"a new {run_name} call."
    )


def continues_note(cell_id: int, wait_name: str) -> str:
    return (
        f"Cell {cell_id} continues. Call {wait_name}(cell_id={cell_id}) for more "
        f"output, or {wait_name}(cell_id={cell_id}, terminate=true) to stop it."
    )


class CellContent(NamedTuple):
    """The text that the model reads for one window of a cell."""

    text: str
    # When the budget cut text from the sections after the heading (the
    # printed output, the result, the error): those sections, uncut.
    full_value: str | None


def format_content(
    window: CellWindow,
    *,
    heading: str,
    status: CodeModeStatus,
    cell_id: int,
    wait_name: str,
    cell_calls: Sequence[CodeModeCall],
    max_chars: int,
    end: SandboxResult | None,
    discarded: DiscardedWrites | None,
    elided_chars: int,
    lost_store_writes: LostStoreWrites | None = None,
) -> CellContent:
    """The text the model reads for one window of a cell: an observation, or
    the closing record after the last one. `heading` is its first line.

    `cell_calls` are every call of the cell, also those of earlier windows; a
    window that reports a program that did not complete lists them, since they
    may have had effects. `end` and `discarded` (store() writes that did not
    commit) are set when the window reports the program's end. The output
    sections share `max_chars` with the notes after them and are cut once in
    the middle, with a warning that gives the original character count.
    `elided_chars` were cut from the middle of the printed text before this;
    the count includes them. `lost_store_writes` are earlier commits that the
    store dropped. The notes of a window that reports the cell running end
    with how to continue it with the shape's wait tool, `wait_name`.
    """
    completed = status == "completed"
    running = status == "running"
    sections = [heading]
    if window.stdout:
        sections.append(f"Output:\n{window.stdout.rstrip()}")
    if window.result is not None:
        sections.append(f"Result:\n{window.result}")
    if window.error:
        sections.append(f"Error:\n{window.error}")
    if end is not None and end.type_check_notes:
        sections.append(f"Type checker notes:\n{end.type_check_notes}")
    if completed and not window.stdout and window.result is None:
        sections.append("Output: (none). Print the values you need.")
    note_text = "\n\n".join(
        note
        for note in (
            None if completed or running else calls_note(cell_calls),
            images_note(window.calls),
            None if end is None else _unawaited_note(_call_names(end.unawaited_calls)),
            None if end is None else _unstarted_note(_call_names(end.unstarted_calls)),
            None if lost_store_writes is None else lost_store_writes.note,
            None if discarded is None else discarded.note,
            None if window.commit is None else store_summary(window.commit.writes),
            continues_note(cell_id, wait_name) if running else None,
        )
        if note
    )
    note_text = truncate_output(
        note_text, MAX_NOTES_CHARS, label="code mode notes", keep_tail=True
    )
    text = "\n\n".join(sections)
    max_text_chars = max(0, max_chars - len(note_text))
    full_value = None
    if len(text) > max_text_chars:
        count = len(text) + elided_chars
        head_chars = max_text_chars // 2
        tail_start = len(text) - (max_text_chars - head_chars)
        # The sections after the heading start after its "\n\n" separator.
        if tail_start > len(heading) + 2:
            full_value = "\n\n".join(sections[1:])
        text = (
            f"Warning: truncated output (original character count: {count})\n"
            f"Total output lines: {text.count('\n') + 1}\n\n"
            f"{text[:head_chars]}{truncation_marker(count - max_text_chars)}"
            f"{text[tail_start:]}"
        )
    return CellContent(
        text=f"{text}\n\n{note_text}" if note_text else text, full_value=full_value
    )
