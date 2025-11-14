import json
from collections.abc import Generator
from typing import Any
from typing import cast

from onyx.db.enums import MCPAuthenticationType
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool import CUSTOM_TOOL_RESPONSE_ID
from onyx.tools.tool_implementations.custom.custom_tool import CustomToolCallSummary
from onyx.tools.tool_implementations.mcp.mcp_client import call_mcp_tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

MCP_TOOL_RESPONSE_ID = "mcp_tool_response"

# TODO: for now we're fitting MCP tool responses into the CustomToolCallSummary class
# In the future we may want custom handling for MCP tool responses
# class MCPToolCallSummary(BaseModel):
#     tool_name: str
#     server_url: str
#     tool_result: Any
#     server_name: str


class MCPTool(Tool[None, None]):
    """Tool implementation for MCP (Model Context Protocol) servers"""

    def __init__(
        self,
        tool_id: int,
        mcp_server: MCPServer,  # TODO: these should be basemodels instead of db objects
        tool_name: str,
        tool_description: str,
        tool_definition: dict[str, Any],
        connection_config: MCPConnectionConfig | None = None,
        user_email: str = "",
    ) -> None:
        self._id = tool_id
        self.mcp_server = mcp_server
        self.connection_config = connection_config
        self.user_email = user_email

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

    def get_llm_tool_response(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Build message content from tool response"""
        response = cast(CustomToolCallSummary, args[0].response)
        # For now, just return the JSON result
        # Future versions might handle base64 content differently
        return json.dumps(response.tool_result)

    def run(
        self, override_kwargs: dict[str, Any] | None = None, **kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        """Execute the MCP tool by calling the MCP server"""
        try:
            # Build headers from connection config; prefer explicit headers
            headers: dict[str, str] = (
                self.connection_config.config["headers"]
                if self.connection_config
                else {}
            )

            # Check if this is an authentication issue before making the call
            requires_auth = (
                self.mcp_server.auth_type != MCPAuthenticationType.NONE
                and self.mcp_server.auth_type is not None
            )
            has_auth_config = self.connection_config is not None and bool(headers)

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

                yield ToolResponse(
                    id=CUSTOM_TOOL_RESPONSE_ID,
                    response=CustomToolCallSummary(
                        tool_name=self._name,
                        response_type="json",
                        tool_result={"error": auth_error_msg},
                    ),
                )
                return

            tool_result = call_mcp_tool(
                self.mcp_server.server_url,
                self._name,
                kwargs,
                connection_headers=headers,
                transport=self.mcp_server.transport,
            )

            logger.info(f"MCP tool '{self._name}' executed successfully")

            yield ToolResponse(
                id=CUSTOM_TOOL_RESPONSE_ID,
                response=CustomToolCallSummary(
                    tool_name=self._name,
                    response_type="json",
                    tool_result=json.dumps({"tool_result": tool_result}),
                ),
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

            # Return error as tool result
            yield ToolResponse(
                id=CUSTOM_TOOL_RESPONSE_ID,
                response=CustomToolCallSummary(
                    tool_name=self._name,
                    response_type="json",
                    tool_result=error_result,
                ),
            )

    def get_final_result(self, *args: ToolResponse) -> JSON_ro:
        """Return the final result for storage in the database"""
        response = cast(CustomToolCallSummary, args[0].response)
        return response.tool_result
