import json
from collections.abc import Generator
from typing import Any
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.db.enums import MCPAuthenticationType
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.base_tool import BaseTool
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
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


class MCPTool(BaseTool):
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

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Build message content from tool response"""
        response = cast(CustomToolCallSummary, args[0].response)
        # For now, just return the JSON result
        # Future versions might handle base64 content differently
        return json.dumps(response.tool_result)

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        """Get arguments for non-tool-calling LLMs using prompt-based extraction"""

        # Simple implementation for now - in production this would use more sophisticated prompting
        if not force_run:
            # Basic check if we should use this tool
            should_use_prompt = f"""
Should the following query use the {self._name} tool from mcp server {self.mcp_server.name}?
Tool description: {self._description}
Query: {query}

Answer with 'YES' or 'NO' only.
"""
            should_use_result = llm.invoke(
                [
                    SystemMessage(
                        content="You are a helpful assistant that determines if a tool should be used."
                    ),
                    HumanMessage(content=should_use_prompt),
                ]
            )

            if "YES" not in cast(str, should_use_result.content).upper():
                return None

        # Extract arguments using the tool schema
        args_prompt = f"""
Extract the arguments for the {self._name} tool from the following query.
Tool description: {self._description}
Tool parameters: {json.dumps(self._tool_definition.get('inputSchema', {}), indent=2)}
Query: {query}
Chat history: {history}

Return ONLY a valid JSON object with the extracted arguments. If no arguments are needed, return {{}}.
"""

        args_result = llm.invoke(
            [
                SystemMessage(
                    content="You are a helpful assistant that extracts tool arguments from user queries."
                ),
                HumanMessage(content=args_prompt),
            ]
        )

        args_result_str = cast(str, args_result.content)

        try:
            return json.loads(args_result_str.strip())
        except json.JSONDecodeError:
            # Try removing code block markers
            try:
                cleaned = (
                    args_result_str.strip().strip("```").strip("json").strip("```")
                )
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to parse args for MCP tool '{self._name}'. Received: {args_result_str}"
                )
                return {}

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

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Return the final result for storage in the database"""
        response = cast(CustomToolCallSummary, args[0].response)
        return response.tool_result

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        """Build the next prompt with MCP tool results"""

        # For now, use the default behavior from BaseTool
        # Future versions could add MCP-specific prompt building
        return super().build_next_prompt(
            prompt_builder,
            tool_call_summary,
            tool_responses,
            using_tool_calling_llm,
        )
