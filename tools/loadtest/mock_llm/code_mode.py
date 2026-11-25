"""Code mode wire contract: the programs the mock writes and the results it reads.

With CODE_MODE_ENABLED, Onyx offers a run tool instead of retrieval tools: a
model whose name contains "claude" gets `repl` and `poll`, every other model
`exec` and `wait` (backend code_mode/shapes.py). The run tool's `code`
argument is a Python program in which each tool is an async function of the
`tools` namespace.
The program's printed output, under an "Execution <status> in cell N" header,
is the tool result that the model reads. A program that runs past its yield time
returns "Execution running in cell N"; the wait tool with `cell_id=N`
continues it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from mock_llm.models import ChatMessage, ToolDefinition, content_text

# Each tool family's run tool, and the tool that waits on its cells. Onyx picks
# the family from the model's names (LLMConfig.tool_family in
# backend/onyx/llm/interfaces.py, model_capabilities.is_claude_model); keep in
# sync with backend code_mode/shapes.py.
WAIT_TOOLS = {"exec": "wait", "repl": "poll"}
# A planned program failure raises this message; the load client does not
# count it as a failed turn (onyx_client/stream_parser.py).
PLANNED_FAILURE = "mock_planned_failure"
# Text that programs without searches print.
_FILLER_LINE = "Synthetic program output for load testing.\n"

# Retrieval functions that take `queries` and return numbered search results.
QUERY_FUNCTIONS = ("internal_search", "web_search")

_FUNCTION_RE = re.compile(r"async def (\w+)\(")
_ENVELOPE_RE = re.compile(r"^Execution [a-z ]+ in cell (\d+) ", re.MULTILINE)
_RUNNING_RE = re.compile(r"^Execution running in cell (\d+) ", re.MULTILINE)
_OUTPUT_RE = re.compile(r"(?:^|\n\n)Output:\n(.*?)(?:\n\n|\Z)", re.DOTALL)
# One line per result that search_program prints.
_DOCUMENT_LINE_RE = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


def code_functions(tool: ToolDefinition) -> set[str]:
    """Functions that the run tool's description lists as stubs."""
    return set(_FUNCTION_RE.findall(tool.function.description or ""))


def run_tool(by_name: dict[str, ToolDefinition]) -> ToolDefinition | None:
    """The offered run tool of either family."""
    return next((by_name[name] for name in WAIT_TOOLS if name in by_name), None)


def _searches_head(searches: Sequence[tuple[str, Sequence[str]]]) -> str:
    """Statements that run each (function, queries) search into `results`, in
    parallel when there are several."""
    calls = [f"tools.{name}(queries={list(queries)!r})" for name, queries in searches]
    if len(calls) == 1:
        return f"results = [await {calls[0]}]\n"
    return (
        "import asyncio\n"
        "results = await asyncio.gather(\n"
        + "".join(f"    {call},\n" for call in calls)
        + ")\n"
    )


def search_program(searches: Sequence[tuple[str, Sequence[str]]]) -> str:
    """A program that runs each (function, queries) search and prints one
    `[document] title` line per result."""
    return _searches_head(searches) + (
        "for result in results:\n"
        '    for doc in result["results"]:\n'
        '        title = " ".join(doc["title"].split())\n'
        "        print(f\"[{doc['document']}] {title}\")\n"
    )


def profile_program(
    queries: Sequence[Sequence[str]], output_chars: int, failed: bool
) -> str:
    """A program that prints about `output_chars` characters.

    With searches, it runs one internal_search per query list and prints each
    result's `[document] title` line and its content, indented so that no
    content line reads as a document line, cut at `output_chars`. Retrieved
    content shorter than that prints in full. Without searches, it prints
    filler text. A failed program then raises PLANNED_FAILURE."""
    if queries:
        code = _searches_head([("internal_search", q) for q in queries]) + (
            "lines = []\n"
            "for result in results:\n"
            '    for doc in result["results"]:\n'
            '        title = " ".join(doc["title"].split())\n'
            "        lines.append(f\"[{doc['document']}] {title}\")\n"
            '        lines.append("  " + doc["content"].replace("\\n", "\\n  "))\n'
            f'print("\\n".join(lines)[:{output_chars}])\n'
        )
    elif output_chars:
        repeats = output_chars // len(_FILLER_LINE) + 1
        code = f"print(({_FILLER_LINE!r} * {repeats})[:{output_chars}])\n"
    else:
        code = "pass\n"
    if failed:
        code += f"raise RuntimeError({PLANNED_FAILURE!r})\n"
    return code


def citation_ids(content: str) -> set[int]:
    """Document numbers from the printed output of one code mode observation.

    Only `[n] ` at the start of an output line counts, so document prose in a
    title never adds a number.
    """
    if _ENVELOPE_RE.search(content) is None:
        return set()
    match = _OUTPUT_RE.search(content)
    if match is None:
        return set()
    return {
        int(number)
        for number in _DOCUMENT_LINE_RE.findall(match.group(1))
        if int(number) > 0
    }


def running_cell(turn: Sequence[ChatMessage]) -> int | None:
    """The cell to wait for when the turn's latest tool result left it running."""
    for message in reversed(turn):
        if message.role != "tool":
            continue
        text = content_text(message.content)
        match = _RUNNING_RE.search(text) if text is not None else None
        return int(match.group(1)) if match else None
    return None
