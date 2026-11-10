"""Text that the model reads for code mode: tool descriptions and each result."""

import json
from collections.abc import Sequence

from onyx.agents.compaction import count_tokens, head_and_tail_tokens
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
)
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
from onyx.tools.tool_implementations.utils import truncate_output

# Characters of the notes after the output; they are never cut by the budget.
MAX_NOTES_CHARS = 10_000


def _limits_text(limits: SandboxLimits) -> str:
    return (
        f"{limits.max_cpu_seconds:g} seconds of computation, "
        f"{limits.max_tool_calls} tool calls, and "
        f"{limits.max_memory_bytes // (1024 * 1024)} MB of memory"
    )


def _deferred_note(stubs: ToolStubs) -> str:
    groups = [
        *(f"the MCP server `{namespace}`" for namespace in stubs.deferred_namespaces),
        *(["other tools"] if stubs.has_deferred_functions_without_namespace else []),
    ]
    return (
        f"\n- More functions are available than the ones listed below: those of "
        f"{', '.join(groups)}. Find them with `await tool_search(query)`; each match has "
        "the function's name, description and stub. Read the stub before you call "
        "a function, then call it like a listed one, in this program or a later one."
    )


def code_mode_description(stubs: ToolStubs, limits: SandboxLimits) -> str:
    """Model-facing description; deterministic for a given set of tools and limits."""
    deferred_note = _deferred_note(stubs) if stubs.tool_index is not None else ""
    return f"""Run a Python program that calls the tools listed below. Use it to combine tool calls in one step, run independent calls in parallel, and filter large results before you read them.

- The program runs in Monty, a sandboxed Python interpreter, not CPython. It has no file system, network, environment, or subprocess access. Get outside data only through the tool functions.
- Each tool is an async Python function. Call it with keyword arguments only and `await` the result, for example `result = await tool_name(argument=value)`. Top-level `await` works; do not call `asyncio.run()`.
- Await every call; calls that are not awaited are cancelled when the program ends.
- Run independent calls in parallel with `asyncio.gather`, for example `a, b = await asyncio.gather(f(x=1), g(y=2))`. Make a call that needs an earlier result after that result is available.
- `asyncio.gather` takes no keyword arguments, so `return_exceptions=True` is not available, and one failed call fails the whole gather. To keep the other results, wrap each call:
  `async def attempt(call):`
  `    try: return await call`
  `    except Exception as e: return {{"error": str(e)}}`
  `results = await asyncio.gather(*(attempt(f(x=v)) for v in values))`
- Only text that the program prints and the value of the last expression come back to you; that value must be JSON data ({JSON_TYPES_TEXT}). Tool results stay inside the program until you print them. Print only the fields you need, such as titles, document numbers, URLs, and short excerpts. Do not print whole results.
- A tool error raises an exception in the program. To continue after an error, use `try:` / `except Exception as e:`. An uncaught exception stops the program and returns its traceback with the output printed before it.
- Each `execute_code` call starts a fresh interpreter: variables, functions, and imports from earlier calls are gone. To keep a value for a later call, `store(key, value)` it, then `load(key)` it in the later call. `load` returns None for a missing key. `store`, `load` and `yield_control` are plain functions: do not `await` them.
- Stored values stay available in all later `execute_code` calls of this chat, also in later messages. Store only JSON values ({JSON_TYPES_TEXT}). Storing None deletes the key. A program saves its writes when it ends by itself: it completes, or stops at an uncaught exception. Later programs see them from then on. The writes of a program that is terminated or times out are discarded. Each value can be up to {MAX_STORED_VALUE_BYTES // 1024} KB as JSON, and the whole store up to {MAX_STORE_BYTES // (1024 * 1024)} MB. Store values that you plan to reuse, such as IDs, totals, or filtered results, instead of calling the tools again.
- Each program is limited to {_limits_text(limits)}.
- A program that runs longer than `yield_time_ms`, or that calls `yield_control()`, returns its output so far and keeps running as cell N. Call `wait_code` with the cell id to get more output or to stop the cell. Do other work while a cell runs. Open cells stop when you give your final answer, so wait for each cell whose result you need first. A cell stops after {limits.lifetime_seconds / 60:g} minutes.
- Supported Python: functions, closures, lambdas, comprehensions, f-strings, `try`/`except`/`finally`, `match`, `@dataclass`, and classes without base classes. Not supported: class inheritance, custom exception classes (catch `Exception`), generators (`yield`), `del`, and `async with`.
- These modules are already imported in every program: {", ".join(IMPORTABLE_MODULES)}. Other modules are not available.
- The program is type-checked before it runs. A wrong argument name or type in a tool call stops the program before any tool runs.
- Search results have a `document` number. To cite a result in your answer, print its `document` number and write [n] in the answer, where n is that number.{deferred_note}

Functions (already defined in every program; call them directly, no import needed):
```python
{stubs.listed_text.rstrip()}
```"""


WAIT_CODE_DESCRIPTION = """Waits on a running `execute_code` cell and returns new output or completion.
- Use `wait_code` only after `execute_code` returns `Execution running in cell N`.
- `wait_code` returns only the new output since the last result for that cell, or the final completion or termination result.
- If the cell is still running, `wait_code` may return again with the same `cell_id`.
- If the cell has already finished, `wait_code` returns the completed result and closes the cell."""


def program_function_operation(name: str, *, deferred: bool) -> str:
    """How a tool preference names a function of `execute_code` programs."""
    found = "; find its stub with `await tool_search(query)`" if deferred else ""
    return f"{name} (a function in `execute_code` programs{found})"


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


def continues_note(cell_id: int) -> str:
    return (
        f"Cell {cell_id} continues. Call wait_code(cell_id={cell_id}) for more output, "
        f"or wait_code(cell_id={cell_id}, terminate=true) to stop it."
    )


def token_budget(text: str, max_tokens: int, *, elided_chars: int = 0) -> str:
    """`text` within `max_tokens`, cut in the middle with a warning that gives
    the original token count.

    `elided_chars` were already cut from the middle of `text`; the count
    estimates their tokens at the ratio of `text`.
    """
    head, tail, count = head_and_tail_tokens(text, max_tokens)
    if count <= max_tokens:
        return text
    if elided_chars:
        count += round(elided_chars * count / max(1, len(text)))
    lines = text.count("\n") + 1
    return (
        f"Warning: truncated output (original token count: {count})\n"
        f"Total output lines: {lines}\n\n"
        f"{head}…{count - max_tokens} tokens truncated…{tail}"
    )


def format_content(
    window: CellWindow,
    *,
    heading: str,
    status: CodeModeStatus,
    cell_id: int,
    cell_calls: Sequence[CodeModeCall],
    max_tokens: int,
    end: SandboxResult | None,
    discarded: DiscardedWrites | None,
    elided_chars: int,
    lost_store_writes: LostStoreWrites | None = None,
) -> str:
    """The text the model reads for one window of a cell: an observation, or
    the closing record after the last one. `heading` is its first line.

    `cell_calls` are every call of the cell, also those of earlier windows; a
    window that reports a program that did not complete lists them, since they
    may have had effects. `end` and `discarded` (store() writes that did not
    commit) are set when the window reports the program's end. The output
    sections share `max_tokens` with the notes after them and are cut once.
    `elided_chars` were cut from the middle of the printed text before this.
    `lost_store_writes` are earlier commits that the store dropped.
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
            continues_note(cell_id) if running else None,
        )
        if note
    )
    note_text = truncate_output(
        note_text, MAX_NOTES_CHARS, label="code mode notes", keep_tail=True
    )
    text = token_budget(
        "\n\n".join(sections),
        max(0, max_tokens - (count_tokens(note_text) if note_text else 0)),
        elided_chars=elided_chars,
    )
    return f"{text}\n\n{note_text}" if note_text else text
