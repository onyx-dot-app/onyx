"""Tools that drive the chat's browser tabs through a `BrowserBackend`: the
browser service in the sandbox VM (`SandboxBrowser`), or the user's own
Chrome through the Onyx extension (`onyx/browser_extension/relay.py:ChromeBrowser`).
Both take the same methods and params and give the same result shapes, so the
tools do not know which browser answers. Each chat sees and acts on its own
tabs only. A tab that the user controls refuses agent writes with a message
that tells the model what to do.

A turn offers them when the admin setting `browser_enabled` is on
(`ChatTurnSetup.browser_target`). The web panel opens itself on the start
packet of a `browser_open` call, so that name must stay.
"""

import abc
import json

from pydantic import JsonValue

from onyx.agents.tools import ToolExecutionMode, ToolInvocation
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.prompts.browser_tools import (
    BROWSER_ACT_DESCRIPTION,
    BROWSER_DIALOG_DESCRIPTION,
    BROWSER_EVALUATE_DESCRIPTION,
    BROWSER_NAVIGATE_DESCRIPTION,
    BROWSER_OPEN_DESCRIPTION,
    BROWSER_OPEN_DESCRIPTION_CHROME,
    BROWSER_SNAPSHOT_DESCRIPTION,
    BROWSER_SNAPSHOT_DESCRIPTION_CHROME,
    BROWSER_STATUS_DESCRIPTION,
    BROWSER_WAIT_FOR_DESCRIPTION,
)
from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandboxError,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    ToolApprovalDetails,
    ToolApprovalScope,
    ToolCallException,
    ToolContext,
)
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.sandbox.errors import (
    sandbox_errors_as_tool_errors,
)
from onyx.tools.tool_implementations.sandbox.models import (
    BROWSER_DEFAULT_TIMEOUT_MS,
    BrowserActArguments,
    BrowserArguments,
    BrowserDialogArguments,
    BrowserEvaluateArguments,
    BrowserNavigateArguments,
    BrowserOpenArguments,
    BrowserSnapshotArguments,
    BrowserStatusArguments,
    BrowserTarget,
    BrowserTimeoutArguments,
    BrowserWaitForArguments,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.utils import truncate_output

# Time that a call gets beyond the browser's own wait: the hop to it.
_CALL_MARGIN_SECONDS = 15.0
# Largest result text that the model gets.
BROWSER_RESULT_MAX_CHARS = 80_000

# The user's Chrome asks once per site; the call's details name the site's
# action (ChromeBrowser.site_approval). A turn that runs without asking builds
# the tools without it (chat/execution.py).
CHROME_SITE_APPROVAL = ToolApprovalScope(
    integration_id=None, action_id="onyx:chrome.site"
)

_INTERRUPTED_BROWSER_MESSAGE = (
    "The call was interrupted before it returned and was not run again. "
    "Check the page with browser_status or browser_snapshot before you retry."
)


class BrowserBackend(abc.ABC):
    """One browser that answers the browser tools' calls."""

    target: BrowserTarget

    @abc.abstractmethod
    def call(
        self, method: str, params: dict[str, JsonValue], *, timeout_seconds: float
    ) -> dict[str, JsonValue]:
        """The result of one call. Raises ToolCallException with a message
        for the model when the browser refuses or does not answer."""
        raise NotImplementedError

    def site_approval(
        self,
        method: str,  # noqa: ARG002
        params: dict[str, JsonValue],  # noqa: ARG002
    ) -> ToolApprovalDetails | None:
        """The approval card of a call that acts on a site that the user has
        not allowed yet, or None when the call needs none."""
        return None


class SandboxBrowser(BrowserBackend):
    """The browser service in the user's sandbox VM."""

    target = BrowserTarget.SANDBOX

    def __init__(self, turn: SandboxTurn) -> None:
        self._turn = turn

    def call(
        self, method: str, params: dict[str, JsonValue], *, timeout_seconds: float
    ) -> dict[str, JsonValue]:
        with sandbox_errors_as_tool_errors():
            ref = self._turn.start_call()
            return self._turn.sandbox.browser_call(
                ref,
                method,
                _with_session_paths(ref, params),
                timeout_seconds=timeout_seconds,
            )


def _session_path(ref: HarnessSandboxRef, path: str) -> str:
    """A path in the chat session directory, as the service takes it."""
    relative = session_relative_path(ref.session_id, path)
    if not relative:
        raise HarnessSandboxError(f"{path!r} is the working directory, not a file")
    return relative


def _with_session_paths(
    ref: HarnessSandboxRef, params: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """The params with their working-directory paths made session-relative."""
    update: dict[str, JsonValue] = {}
    paths = params.get("paths")
    if isinstance(paths, list):
        update["paths"] = [_session_path(ref, str(path)) for path in paths]
    screenshot_path = params.get("screenshotPath")
    if isinstance(screenshot_path, str):
        update["screenshotPath"] = _session_path(ref, screenshot_path)
    return {**params, **update}


class BrowserTool[ArgumentsT: BrowserArguments](Tool):
    """What the browser tools share: one browser call per tool call, taken
    in turns, since the calls of one step act on the same tabs. A read runs
    again after a lost server (RUNS_AGAIN); a call that changes a tab does
    not."""

    id = None
    rank = ToolRank.BROWSER
    sequence_group = "sandbox_browser"
    NAME: str
    DESCRIPTION: str
    # The description for the user's Chrome, when it differs.
    CHROME_DESCRIPTION: str | None = None
    ARGUMENTS: type[ArgumentsT]
    METHOD: str
    DISPLAY_NAME: str
    RUNS_AGAIN = False

    def __init__(self, backend: BrowserBackend) -> None:
        self._backend = backend
        if backend.target is BrowserTarget.CHROME:
            self.approval = CHROME_SITE_APPROVAL
        if not self.RUNS_AGAIN:
            self.interrupted_result = ToolResult(
                content=_INTERRUPTED_BROWSER_MESSAGE, is_error=True
            )

    @property
    def target(self) -> BrowserTarget:
        return self._backend.target

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.describe_for(self._backend.target)

    @classmethod
    def describe_for(cls, target: BrowserTarget) -> str:
        if target is BrowserTarget.CHROME and cls.CHROME_DESCRIPTION is not None:
            return cls.CHROME_DESCRIPTION
        return cls.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, self.ARGUMENTS, strict=True
        )

    def _params(self, arguments: ArgumentsT) -> tuple[dict[str, JsonValue], int]:
        """The browser params of a call (the set arguments, in camelCase),
        and the browser's wait in ms."""
        wait_ms = BROWSER_DEFAULT_TIMEOUT_MS
        update: dict[str, object] = {}
        if isinstance(arguments, BrowserTimeoutArguments):
            if arguments.timeout_ms is not None:
                wait_ms = arguments.timeout_ms
            update["timeout_ms"] = wait_ms
        params = arguments.model_copy(update=update).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        return params, wait_ms

    def approval_details(
        self, arguments: dict[str, JsonValue]
    ) -> ToolApprovalDetails | None:
        try:
            parsed = parse_tool_arguments(self.ARGUMENTS, arguments)
        except ToolCallException:
            return None
        params, _ = self._params(parsed)
        return self._backend.site_approval(self.METHOD, params)

    def _content(self, result: dict[str, JsonValue]) -> str:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(self.ARGUMENTS, invocation.arguments)
        params, wait_ms = self._params(arguments)
        result = self._backend.call(
            self.METHOD,
            params,
            timeout_seconds=wait_ms / 1000 + _CALL_MARGIN_SECONDS,
        )
        content = self._content(result)
        return ToolResult(
            content=truncate_output(content, BROWSER_RESULT_MAX_CHARS, self.NAME),
            # The spill keeps what the cut left out.
            full_value=content if len(content) > BROWSER_RESULT_MAX_CHARS else None,
        )


class BrowserStatusTool(BrowserTool[BrowserStatusArguments]):
    NAME = "browser_status"
    DISPLAY_NAME = "Browser Status"
    DESCRIPTION = BROWSER_STATUS_DESCRIPTION
    ARGUMENTS = BrowserStatusArguments
    METHOD = "status"
    RUNS_AGAIN = True


class BrowserOpenTool(BrowserTool[BrowserOpenArguments]):
    # The web panel opens itself on a call of this name.
    NAME = "browser_open"
    DISPLAY_NAME = "Open Page"
    DESCRIPTION = BROWSER_OPEN_DESCRIPTION
    CHROME_DESCRIPTION = BROWSER_OPEN_DESCRIPTION_CHROME
    ARGUMENTS = BrowserOpenArguments
    METHOD = "open"


class BrowserNavigateTool(BrowserTool[BrowserNavigateArguments]):
    NAME = "browser_navigate"
    DISPLAY_NAME = "Navigate Page"
    DESCRIPTION = BROWSER_NAVIGATE_DESCRIPTION
    ARGUMENTS = BrowserNavigateArguments
    METHOD = "navigate"


class BrowserSnapshotTool(BrowserTool[BrowserSnapshotArguments]):
    NAME = "browser_snapshot"
    DISPLAY_NAME = "Read Page"
    DESCRIPTION = BROWSER_SNAPSHOT_DESCRIPTION
    CHROME_DESCRIPTION = BROWSER_SNAPSHOT_DESCRIPTION_CHROME
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


class BrowserActTool(BrowserTool[BrowserActArguments]):
    NAME = "browser_act"
    DISPLAY_NAME = "Use Page"
    DESCRIPTION = BROWSER_ACT_DESCRIPTION
    ARGUMENTS = BrowserActArguments
    METHOD = "act"


class BrowserWaitForTool(BrowserTool[BrowserWaitForArguments]):
    NAME = "browser_wait_for"
    DISPLAY_NAME = "Wait For Page"
    DESCRIPTION = BROWSER_WAIT_FOR_DESCRIPTION
    ARGUMENTS = BrowserWaitForArguments
    METHOD = "waitFor"
    RUNS_AGAIN = True


class BrowserEvaluateTool(BrowserTool[BrowserEvaluateArguments]):
    NAME = "browser_evaluate"
    DISPLAY_NAME = "Run Page Script"
    DESCRIPTION = BROWSER_EVALUATE_DESCRIPTION
    ARGUMENTS = BrowserEvaluateArguments
    METHOD = "evaluate"


class BrowserDialogTool(BrowserTool[BrowserDialogArguments]):
    NAME = "browser_dialog"
    DISPLAY_NAME = "Answer Page Dialog"
    DESCRIPTION = BROWSER_DIALOG_DESCRIPTION
    ARGUMENTS = BrowserDialogArguments
    METHOD = "dialog"


# The browser tools; browser_open carries the use. Within their rank the
# turn orders them by name (onyx/tools/ordering.py).
BROWSER_TOOLS: tuple[type[BrowserTool], ...] = (
    BrowserOpenTool,
    BrowserNavigateTool,
    BrowserSnapshotTool,
    BrowserActTool,
    BrowserWaitForTool,
    BrowserEvaluateTool,
    BrowserStatusTool,
    BrowserDialogTool,
)


def browser_tools_for(target: BrowserTarget) -> tuple[type[BrowserTool], ...]:
    """The tools that a browser offers. The user's Chrome runs no page
    scripts: the extension refuses them, so the model does not get the tool."""
    if target is BrowserTarget.CHROME:
        return tuple(tool for tool in BROWSER_TOOLS if tool is not BrowserEvaluateTool)
    return BROWSER_TOOLS


def build_browser_tools(backend: BrowserBackend) -> list[Tool]:
    return [tool(backend) for tool in browser_tools_for(backend.target)]
