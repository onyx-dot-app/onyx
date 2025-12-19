import json
from typing import Any

from onyx.chat.emitter import Emitter
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.mcp.mcp_client import call_mcp_tool
from onyx.utils.logger import setup_logger

logger = setup_logger()

# TODO: for now we're fitting MCP tool responses into the CustomToolCallSummary class
# In the future we may want custom handling for MCP tool responses
# class MCPToolCallSummary(BaseModel):
#     tool_name: str
#     server_url: str
#     tool_result: Any
#     server_name: str


class MCPTool(Tool[None]):
    """Tool implementation for MCP (Model Context Protocol) servers"""

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        mcp_server: MCPServer,  # TODO: these should be basemodels instead of db objects
        tool_name: str,
        tool_description: str,
        tool_definition: dict[str, Any],
        connection_config: MCPConnectionConfig | None = None,
        user_email: str = "",
        user_oauth_token: str | None = None,
    ) -> None:
        super().__init__(emitter=emitter)

        self._id = tool_id
        self.mcp_server = mcp_server
        self.connection_config = connection_config
        self.user_email = user_email
        self._user_oauth_token = user_oauth_token

        self._name = tool_name
        self._tool_definition = tool_definition
        self._description = tool_description
        self._display_name = tool_definition.get("displayName", tool_name)
        self._llm_name = f"mcp:{mcp_server.name}:{tool_name}"

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def llm_name(self) -> str:
        return self._llm_name

    def tool_definition(self) -> dict:
        """Return the tool definition from the MCP server"""
        # Convert MCP tool definition to OpenAI function calling format
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": self._tool_definition,
            },
        }

    def emit_start(self, turn_index: int, tab_index: int) -> None:
        self.emitter.emit(
            Packet(
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=CustomToolStart(tool_name=self._name),
            )
        )

    def run(
        self,
        turn_index: int,
        tab_index: int,
        override_kwargs: None = None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the MCP tool by calling the MCP server"""
        try:
            # Build headers from connection config; prefer explicit headers
            headers: dict[str, str] = (
                self.connection_config.config["headers"]
                if self.connection_config
                else {}
            )

            # For pass-through OAuth, use the user's login OAuth token
            if self._user_oauth_token:
                headers["Authorization"] = f"Bearer {self._user_oauth_token}"

            # Check if this is an authentication issue before making the call
            is_passthrough_oauth = (
                self.mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH
            )
            requires_auth = (
                self.mcp_server.auth_type != MCPAuthenticationType.NONE
                and self.mcp_server.auth_type is not None
            )
            has_auth_config = (
                self.connection_config is not None and bool(headers)
            ) or (is_passthrough_oauth and self._user_oauth_token is not None)

            if requires_auth and not has_auth_config:
                # Authentication required but not configured
                auth_error_msg = (
                    f"The {self._name} tool from {self.mcp_server.name} requires authentication "
                    f"but no credentials have been provided. Tell the user to use the MCP dropdown in the "
                    f"chat bar to authenticate with the {self.mcp_server.name} server before "
                    f"using this tool."
                )
                logger.warning(
                    f"Authentication required for MCP tool '{self._name}' but no credentials found"
                )

                error_result = {"error": auth_error_msg}
                llm_facing_response = json.dumps(error_result)

                # Emit CustomToolDelta packet
                self.emitter.emit(
                    Packet(
                        placement=Placement(turn_index=turn_index, tab_index=tab_index),
                        obj=CustomToolDelta(
                            tool_name=self._name,
                            response_type="json",
                            data=error_result,
                        ),
                    )
                )

                return ToolResponse(
                    rich_response=CustomToolCallSummary(
                        tool_name=self._name,
                        response_type="json",
                        tool_result=error_result,
                    ),
                    llm_facing_response=llm_facing_response,
                )

            tool_result = call_mcp_tool(
                self.mcp_server.server_url,
                self._name,
                llm_kwargs,
                connection_headers=headers,
                transport=self.mcp_server.transport or MCPTransport.STREAMABLE_HTTP,
            )

            logger.info(f"MCP tool '{self._name}' executed successfully")

            # Format the tool result for response
            tool_result_dict = {"tool_result": tool_result}
            llm_facing_response = json.dumps(tool_result_dict)

            # Emit CustomToolDelta packet
            self.emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=CustomToolDelta(
                        tool_name=self._name,
                        response_type="json",
                        data=tool_result_dict,
                    ),
                )
            )

            return ToolResponse(
                rich_response=CustomToolCallSummary(
                    tool_name=self._name,
                    response_type="json",
                    tool_result=tool_result_dict,
                ),
                llm_facing_response=llm_facing_response,
            )

        except Exception as e:
            error_str = str(e).lower()
            logger.error(f"Failed to execute MCP tool '{self._name}': {e}")

            # Check for authentication-related errors
            auth_error_indicators = [
                "401",
                "unauthorized",
                "authentication",
                "auth",
                "forbidden",
                "access denied",
                "invalid token",
                "invalid api key",
                "invalid credentials",
            ]

            is_auth_error = any(
                indicator in error_str for indicator in auth_error_indicators
            )

            if is_auth_error:
                auth_error_msg = (
                    f"Authentication failed for the {self._name} tool from {self.mcp_server.name}. "
                    f"Please use the MCP dropdown in the chat bar to update your credentials "
                    f"for the {self.mcp_server.name} server. Original error: {str(e)}"
                )
                error_result = {"error": auth_error_msg}
            else:
                error_result = {"error": f"Tool execution failed: {str(e)}"}

            llm_facing_response = json.dumps(error_result)

            # Emit CustomToolDelta packet
            self.emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=CustomToolDelta(
                        tool_name=self._name,
                        response_type="json",
                        data=error_result,
                    ),
                )
            )

            return ToolResponse(
                rich_response=CustomToolCallSummary(
                    tool_name=self._name,
                    response_type="json",
                    tool_result=error_result,
                ),
                llm_facing_response=llm_facing_response,
            )
