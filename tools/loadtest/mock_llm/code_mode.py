"""Code mode wire contract: the programs the mock writes and the results it reads.

With CODE_MODE_ENABLED, Onyx offers `execute_code` instead of retrieval tools.
Its `code` argument is a Python program in which each tool is an async function.
The program's printed output, under an "Execution <status> in cell N" header,
is the tool result that the model reads. A program that runs past its yield time
returns "Execution running in cell N"; `wait_code(cell_id=N)` continues it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from mock_llm.models import ChatMessage, ToolDefinition

EXECUTE_CODE = "execute_code"
WAIT_CODE = "wait_code"

# Retrieval functions that take `queries` and return numbered search results.
QUERY_FUNCTIONS = ("internal_search", "web_search")

_FUNCTION_RE = re.compile(r"async def (\w+)\(")
_ENVELOPE_RE = re.compile(r"^Execution [a-z ]+ in cell (\d+) ", re.MULTILINE)
_RUNNING_RE = re.compile(r"^Execution running in cell (\d+) ", re.MULTILINE)
_OUTPUT_RE = re.compile(r"(?:^|\n\n)Output:\n(.*?)(?:\n\n|\Z)", re.DOTALL)
# One line per result that search_program prints.
_DOCUMENT_LINE_RE = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


def code_functions(tool: ToolDefinition) -> set[str]:
    """Functions that the execute_code description lists as stubs."""
    return set(_FUNCTION_RE.findall(tool.function.description or ""))


def search_program(searches: Sequence[tuple[str, Sequence[str]]]) -> str:
    """A program that runs each (function, queries) search, in parallel when
    there are several, and prints one `[document] title` line per result."""
    calls = [f"{name}(queries={list(queries)!r})" for name, queries in searches]
    if len(calls) == 1:
        head = f"results = [await {calls[0]}]\n"
    else:
        head = (
            "import asyncio\n"
            "results = await asyncio.gather(\n"
            + "".join(f"    {call},\n" for call in calls)
            + ")\n"
        )
    return head + (
        "for result in results:\n"
        '    for doc in result["results"]:\n'
        '        title = " ".join(doc["title"].split())\n'
        "        print(f\"[{doc['document']}] {title}\")\n"
    )


def is_observation(content: str) -> bool:
    return _ENVELOPE_RE.search(content) is not None


def citation_ids(content: str) -> set[int]:
    """Document numbers from the printed output of one code mode observation.

    Only `[n] ` at the start of an output line counts, so document prose in a
    title never adds a number.
    """
    if not is_observation(content):
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
        if not isinstance(message.content, str):
            return None
        match = _RUNNING_RE.search(message.content)
        return int(match.group(1)) if match else None
    return None
