"""Code node: run a snippet of Python in the sandbox.

The snippet never executes in the worker. Worker processes hold database
credentials, connector secrets and the tenant's whole environment, and a flow
is authored in a browser by anyone who can edit it — so the snippet goes to
the code interpreter service, which is the one place in Onyx built to run
somebody's Python.

Two details of the handover are worth knowing if you ever have to debug it:

**Context arrives on stdin, not baked into the source.** Interpolating a run's
data into a program means escaping it correctly every time forever, and one
stray quote in an API response would be a syntax error at best.

**The result comes back on a marked line of stdout.** The snippet is expected
to ``print`` for its own reasons, so the wrapper writes the JSON result behind
a marker and the last marked line wins. Everything else is kept as ``logs``.
"""

from __future__ import annotations

import json
from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import RunContext
from onyx.flows.models import CodeNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    ExecuteResponse,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Prefix the wrapper writes the JSON result behind. Long and unlovely so a
# snippet does not produce one by accident.
RESULT_MARKER = "__onyx_flow_result__"

# The name the snippet is compiled under, so a traceback points at the
# author's own line numbers.
SNIPPET_FILENAME = "<flow code step>"

# The run's data has to be serialised and shipped, so there is a real limit on
# how much of it a code step can see. Well past any sane flow, and far short of
# what would hurt the sandbox.
MAX_CONTEXT_BYTES = 512 * 1024

# Kept on the node's output for the run view. Prints are for debugging, not
# for storage.
MAX_LOG_CHARS = 8000

# Enough of a traceback to see the exception and where it came from.
MAX_ERROR_CHARS = 1200


def execute_code(
    node: CodeNode, context: RunContext, runtime: NodeRuntime
) -> NodeOutcome:
    """Send the snippet and the run's data to the sandbox, return the result."""
    payload = _serialise_context(context)

    try:
        runner = runtime.code_runner()
    except Exception as exc:
        logger.warning("flow code node has no sandbox node=%s: %s", node.id, exc)
        raise NodeExecutionError(
            FlowErrorClass.CODE_ERROR,
            "the code sandbox is not available — set CODE_INTERPRETER_BASE_URL "
            "to use code steps",
        ) from exc

    try:
        response = runner.execute(
            code=_wrap(node.code),
            stdin=payload,
            timeout_ms=int(node.timeout_seconds * 1000),
        )
    except Exception as exc:
        # Reaching the sandbox is the kind of thing that fails for a second,
        # so this is classed as retryable while a bad snippet is not.
        raise NodeExecutionError(
            FlowErrorClass.NODE_EXCEPTION,
            f"could not reach the code sandbox: {type(exc).__name__}: {exc}",
        ) from exc

    return NodeOutcome(output=_read_response(node, response))


def _read_response(node: CodeNode, response: ExecuteResponse) -> dict[str, Any]:
    if response.timed_out:
        raise NodeExecutionError(
            FlowErrorClass.TIMEOUT,
            f"the snippet ran past its {node.timeout_seconds:.0f}s limit",
        )

    logs, raw_result = _split_output(response.stdout)

    if response.exit_code != 0:
        detail = _readable_traceback(response.stderr) or (
            f"the snippet exited with code {response.exit_code}"
        )
        raise NodeExecutionError(FlowErrorClass.CODE_ERROR, detail)

    if raw_result is None:
        # The snippet exited early without reaching the wrapper's last line.
        # Not an error — it simply produced nothing.
        return {"result": None, "logs": logs}

    try:
        result = json.loads(raw_result)
    except ValueError as exc:
        raise NodeExecutionError(
            FlowErrorClass.CODE_ERROR,
            f"the snippet's result could not be read back: {exc}",
        ) from exc

    return {"result": result, "logs": logs}


def _serialise_context(context: RunContext) -> str:
    """The run's data, as the JSON the snippet reads from stdin."""
    payload = json.dumps(
        {
            "trigger": context.trigger,
            "steps": context.steps,
            "item": context.item,
            "index": context.index,
        },
        default=str,
    )
    if len(payload) > MAX_CONTEXT_BYTES:
        raise NodeExecutionError(
            FlowErrorClass.CODE_ERROR,
            f"this run carries {len(payload)} bytes of data, over the "
            f"{MAX_CONTEXT_BYTES} byte limit for a code step — narrow the "
            "earlier steps' output first",
        )
    return payload


def _wrap(code: str) -> str:
    """Build the program the sandbox actually runs.

    The snippet goes through ``compile`` under its own filename rather than
    being pasted in above a prologue. Line numbers in a traceback then match
    the editor exactly, which is the difference between a usable error and a
    puzzle.
    """
    trailer = (
        '_onyx_sys.stdout.write("\\n' + RESULT_MARKER + ' " + '
        '_onyx_json.dumps(_onyx_scope.get("result"), default=str) + "\\n")'
    )
    return "\n".join(
        [
            "import json as _onyx_json, sys as _onyx_sys",
            '_onyx_ctx = _onyx_json.loads(_onyx_sys.stdin.read() or "{}")',
            "_onyx_scope = {",
            '    "trigger": _onyx_ctx.get("trigger"),',
            '    "steps": _onyx_ctx.get("steps") or {},',
            '    "item": _onyx_ctx.get("item"),',
            '    "index": _onyx_ctx.get("index"),',
            '    "result": None,',
            "}",
            f'exec(compile({code!r}, {SNIPPET_FILENAME!r}, "exec"), _onyx_scope)',
            trailer,
        ]
    )


def _split_output(stdout: str) -> tuple[str, str | None]:
    """Separate the snippet's own printing from the marked result line."""
    logs: list[str] = []
    raw_result: str | None = None

    for line in stdout.splitlines():
        if line.startswith(RESULT_MARKER):
            # Last one wins: a snippet that printed the marker itself cannot
            # displace the wrapper's line, which is always written last.
            raw_result = line[len(RESULT_MARKER) :].strip()
            continue
        logs.append(line)

    return _clip("\n".join(logs).strip(), MAX_LOG_CHARS), raw_result


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… truncated"


def _readable_traceback(stderr: str) -> str:
    """The traceback with the wrapper's own frame taken out.

    Left alone, every error opens with the ``exec(compile(...))`` line and the
    author's whole snippet quoted back at them on one line. Dropping the
    frames above theirs leaves a traceback that reads like the one they would
    get running the snippet locally.
    """
    lines = stderr.strip().splitlines()
    frame_header = f'File "{SNIPPET_FILENAME}"'
    kept = lines
    for position, line in enumerate(lines):
        if frame_header in line:
            kept = [lines[0], *lines[position:]]
            break
    return _tail("\n".join(kept), MAX_ERROR_CHARS)


def _tail(text: str, limit: int) -> str:
    """The end of a traceback, which is where the exception is."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return "… " + stripped[-limit:]
