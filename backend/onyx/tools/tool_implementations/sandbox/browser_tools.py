"""Tools that drive the chat's tabs in the sandbox's browser
(`HarnessSandbox.browser_call`). The browser service in the VM owns Chrome;
each chat sees and acts on its own tabs only. The user can watch the tabs
live and take control of one: agent writes on that tab then fail at once
with the service's message, which tells the model what to do.

The turn offers them after its family's sandbox tools when the admin setting
`browser_enabled` is on (`with_browser_tools`). The web panel opens itself
on the start packet of a `browser_open` call, so that name must stay.
"""

import json
from collections.abc import Sequence

from pydantic import BaseModel, JsonValue

from onyx.agents.tools import ToolExecutionMode, ToolInvocation
from onyx.llm.models import ToolResult
from onyx.prompts.browser_tools import (
    BROWSER_ACT_DESCRIPTION,
    BROWSER_DIALOG_DESCRIPTION,
    BROWSER_EVALUATE_DESCRIPTION,
    BROWSER_NAVIGATE_DESCRIPTION,
    BROWSER_OPEN_DESCRIPTION,
    BROWSER_SNAPSHOT_DESCRIPTION,
    BROWSER_STATUS_DESCRIPTION,
    BROWSER_WAIT_FOR_DESCRIPTION,
)
from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandboxError,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.interface import parse_tool_arguments
from onyx.tools.models import ToolContext
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.sandbox.errors import (
    sandbox_errors_as_tool_errors,
)
from onyx.tools.tool_implementations.sandbox.models import (
    BrowserActArguments,
    BrowserArguments,
    BrowserDialogArguments,
    BrowserEvaluateArguments,
    BrowserNavigateArguments,
    BrowserOpenArguments,
    BrowserSnapshotArguments,
    BrowserStatusArguments,
    BrowserWaitForArguments,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import SandboxTool
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.utils import truncate_output

# The service's default and largest wait of one call.
BROWSER_DEFAULT_TIMEOUT_MS = 15_000
BROWSER_MAX_TIMEOUT_MS = 60_000
# Time that a call gets beyond the service's own wait: the hop to the VM.
_CALL_MARGIN_SECONDS = 15.0
# Largest result text that the model gets.
BROWSER_RESULT_MAX_CHARS = 80_000

_INTERRUPTED_BROWSER_MESSAGE = (
    "The call was interrupted before it returned and was not run again. "
    "Check the page with browser_status or browser_snapshot before you retry."
)


def _timeout_ms(requested: int | None) -> int:
    if requested is None:
        return BROWSER_DEFAULT_TIMEOUT_MS
    return min(max(requested, 1), BROWSER_MAX_TIMEOUT_MS)


def _session_path(ref: HarnessSandboxRef, path: str) -> str:
    """A path in the chat session directory, as the service takes it."""
    relative = session_relative_path(ref.session_id, path)
    if not relative:
        raise HarnessSandboxError(f"{path!r} is the working directory, not a file")
    return relative


class _BrowserTool[ArgumentsT: BrowserArguments](SandboxTool):
    """What the browser tools share: one service call per tool call, taken
    in turns, since the calls of one step act on the same tabs. A read runs
    again after a lost server (RUNS_AGAIN); a call that changes a tab does
    not."""

    rank = ToolRank.BROWSER
    sequence_group = "sandbox_browser"
    ARGUMENTS: type[ArgumentsT]
    METHOD: str
    DISPLAY_NAME: str

    def __init__(self, turn: SandboxTurn) -> None:
        super().__init__(turn)
        if not self.RUNS_AGAIN:
            self.interrupted_result = ToolResult(
                content=_INTERRUPTED_BROWSER_MESSAGE, is_error=True
            )

    @property
    def arguments(self) -> type[BaseModel]:
        return self.ARGUMENTS

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    def _params(
        self, ref: HarnessSandboxRef, arguments: ArgumentsT
    ) -> tuple[dict[str, JsonValue], int]:
        """The service params of a call (the set arguments, in camelCase, with
        session-relative paths), and the service's wait in ms."""
        params = arguments.model_dump(mode="json", by_alias=True, exclude_none=True)
        wait_ms = BROWSER_DEFAULT_TIMEOUT_MS
        if "timeout_ms" in type(arguments).model_fields:
            requested = params.get("timeoutMs")
            wait_ms = _timeout_ms(requested if isinstance(requested, int) else None)
            params["timeoutMs"] = wait_ms
        paths = params.get("paths")
        if isinstance(paths, list):
            params["paths"] = [_session_path(ref, str(path)) for path in paths]
        screenshot_path = params.get("screenshotPath")
        if isinstance(screenshot_path, str):
            params["screenshotPath"] = _session_path(ref, screenshot_path)
        return params, wait_ms

    def _content(self, result: dict[str, JsonValue]) -> str:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(self.ARGUMENTS, invocation.arguments)
        with sandbox_errors_as_tool_errors():
            ref = self._turn.start_call()
            params, wait_ms = self._params(ref, arguments)
            result = self._turn.sandbox.browser_call(
                ref,
                self.METHOD,
                params,
                timeout_seconds=wait_ms / 1000 + _CALL_MARGIN_SECONDS,
            )
        return ToolResult(
            content=truncate_output(
                self._content(result), BROWSER_RESULT_MAX_CHARS, self.NAME
            )
        )


class BrowserStatusTool(_BrowserTool[BrowserStatusArguments]):
    NAME = "browser_status"
    DISPLAY_NAME = "Browser Status"
    DESCRIPTION = BROWSER_STATUS_DESCRIPTION
    ARGUMENTS = BrowserStatusArguments
    METHOD = "status"
    RUNS_AGAIN = True


class BrowserOpenTool(_BrowserTool[BrowserOpenArguments]):
    # The web panel opens itself on a call of this name.
    NAME = "browser_open"
    DISPLAY_NAME = "Open Page"
    DESCRIPTION = BROWSER_OPEN_DESCRIPTION
    ARGUMENTS = BrowserOpenArguments
    METHOD = "open"


class BrowserNavigateTool(_BrowserTool[BrowserNavigateArguments]):
    NAME = "browser_navigate"
    DISPLAY_NAME = "Navigate Page"
    DESCRIPTION = BROWSER_NAVIGATE_DESCRIPTION
    ARGUMENTS = BrowserNavigateArguments
    METHOD = "navigate"


class BrowserSnapshotTool(_BrowserTool[BrowserSnapshotArguments]):
    NAME = "browser_snapshot"
    DISPLAY_NAME = "Read Page"
    DESCRIPTION = BROWSER_SNAPSHOT_DESCRIPTION
    ARGUMENTS = BrowserSnapshotArguments
    METHOD = "snapshot"
    RUNS_AGAIN = True

    def _content(self, result: dict[str, JsonValue]) -> str:
        """The snapshot text as it is; the tab's other fields as JSON."""
        text = result.get("text")
        if not isinstance(text, str):
            return super()._content(result)
        rest = {key: value for key, value in result.items() if key != "text"}
        return f"{super()._content(rest)}\n{text}"


class BrowserActTool(_BrowserTool[BrowserActArguments]):
    NAME = "browser_act"
    DISPLAY_NAME = "Use Page"
    DESCRIPTION = BROWSER_ACT_DESCRIPTION
    ARGUMENTS = BrowserActArguments
    METHOD = "act"


class BrowserWaitForTool(_BrowserTool[BrowserWaitForArguments]):
    NAME = "browser_wait_for"
    DISPLAY_NAME = "Wait For Page"
    DESCRIPTION = BROWSER_WAIT_FOR_DESCRIPTION
    ARGUMENTS = BrowserWaitForArguments
    METHOD = "waitFor"
    RUNS_AGAIN = True


class BrowserEvaluateTool(_BrowserTool[BrowserEvaluateArguments]):
    NAME = "browser_evaluate"
    DISPLAY_NAME = "Run Page Script"
    DESCRIPTION = BROWSER_EVALUATE_DESCRIPTION
    ARGUMENTS = BrowserEvaluateArguments
    METHOD = "evaluate"


class BrowserDialogTool(_BrowserTool[BrowserDialogArguments]):
    NAME = "browser_dialog"
    DISPLAY_NAME = "Answer Page Dialog"
    DESCRIPTION = BROWSER_DIALOG_DESCRIPTION
    ARGUMENTS = BrowserDialogArguments
    METHOD = "dialog"


# The browser tools; browser_open carries the use. Within their rank the
# turn orders them by name (onyx/tools/ordering.py).
BROWSER_TOOLS: tuple[type[SandboxTool], ...] = (
    BrowserOpenTool,
    BrowserNavigateTool,
    BrowserSnapshotTool,
    BrowserActTool,
    BrowserWaitForTool,
    BrowserEvaluateTool,
    BrowserStatusTool,
    BrowserDialogTool,
)


def with_browser_tools(
    tools: Sequence[type[SandboxTool]], *, browser: bool
) -> tuple[type[SandboxTool], ...]:
    """A turn's sandbox tools (`sandbox_tools.py:SANDBOX_TOOLS`), with the
    browser tools after them when `browser` (the `browser_enabled` setting
    when the turn began). The turn builds them, and the token estimate
    counts their descriptions."""
    return (*tools, *BROWSER_TOOLS) if browser else tuple(tools)
