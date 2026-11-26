"""The one chat tool of an app that the user has not connected."""

from onyx.agents.tools import ToolInvocation
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import ConnectionProblem
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CodeModeExposure,
    ToolContext,
)
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.http_request import failed_tool_result
from onyx.tools.tool_name import connect_tool_name


class AppConnectTool(Tool):
    """The one tool of an app that the user can use on the agent and has no
    usable sign-in for. A call tells the model why the app does not work,
    and the chat shows the user a card that opens the sign-in."""

    rank = ToolRank.INTEGRATION

    def __init__(
        self,
        *,
        integration_id: int,
        integration_name: str,
        problem: ConnectionProblem,
        shared: bool,
    ) -> None:
        self._integration_id = integration_id
        self._integration_name = integration_name
        # Only an admin can fix a shared sign-in.
        self._user_can_connect = (
            not shared and problem.code is not ConnectionState.NOT_SET_UP
        )
        self._reason = problem.reason
        self._name = connect_tool_name(integration_id)

    @property
    def id(self) -> int | None:
        return None

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DEFERRED

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return (
            f"{self._integration_name} is available to the user but is not "
            "connected, so you have no other tool for it. Call this tool when "
            f"the user asks for something that needs {self._integration_name}: "
            "it asks the user to connect."
        )

    @property
    def display_name(self) -> str:
        return self._integration_name

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=self.description,
            parameters={"type": "object", "properties": {}},
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        message = (
            f"{self._integration_name} is not connected. The user now sees a "
            "card to connect it. Tell the user to connect and then to send the "
            "request again. Do not call this tool again in this response."
            if self._user_can_connect
            else f"{self._integration_name} cannot sign in: {self._reason} "
            "Tell the user that an admin must fix its sign-in."
        )
        return failed_tool_result(
            tool_name=self._name,
            integration_id=self._integration_id,
            message=message,
            is_auth_error=self._user_can_connect,
        )
