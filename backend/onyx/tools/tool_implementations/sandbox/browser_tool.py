"""The Browser built-in tool row. Attaching it to an agent, and keeping it on
in a chat's tool options, gives a turn the sandbox's browser tools
(`browser_tools.py:BROWSER_TOOLS`); the turn builds those, never this class."""

from collections.abc import Sequence

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation, ToolOutcome
from onyx.db.models import Tool as ToolModel
from onyx.llm.models import ToolDefinition
from onyx.microvm.configs import HARNESS_SANDBOX_ENABLED
from onyx.server.settings.store import load_browser_enabled
from onyx.tools.interface import Tool
from onyx.tools.models import CodeModeExposure, ToolContext, ToolOptions
from onyx.tools.ordering import ToolRank

_NOT_BUILT = "Bug: the sandbox builds the browser tools, not BrowserTool"


class BrowserTool(Tool):
    rank = ToolRank.BROWSER
    NAME = "browser"
    DISPLAY_NAME = "Browser"
    DESCRIPTION = "Browse websites and act on pages in the sandbox's browser."

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        return HARNESS_SANDBOX_ENABLED and load_browser_enabled()

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DIRECT

    @property
    def id(self) -> int | None:
        raise RuntimeError(_NOT_BUILT)

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    def tool_definition(self) -> ToolDefinition:
        raise RuntimeError(_NOT_BUILT)

    @override
    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        raise RuntimeError(_NOT_BUILT)


def offers_browser(
    tools: Sequence[ToolModel], tool_options: ToolOptions | None
) -> bool:
    """Whether an agent with `tools` offers the browser in a turn with
    `tool_options`: it has the enabled Browser tool and the options allow it."""
    return any(
        tool.enabled
        and tool.in_code_tool_id == BrowserTool.__name__
        and (tool_options is None or tool_options.allows_tool(tool.id))
        for tool in tools
    )
