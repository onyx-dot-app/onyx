import json
import time
from typing import Any
from uuid import UUID

from pydantic import JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.db.enums import MCPTransport
from onyx.integrations.call_credentials import (
    CallCredentials,
    mark_api_key_rejected,
    mcp_oauth_provider,
    resolve_call_credentials_by_id,
)
from onyx.integrations.connections import ConnectionProblem
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.server.features.mcp.client import (
    call_mcp_tool,
    has_unauthorized_response,
    process_mcp_result,
)
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
    merge_mcp_headers,
)
from onyx.server.features.mcp.oauth import MCPReauthenticationRequired
from onyx.server.metrics.mcp_client import record_mcp_client_tool_outcome
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeFunctionName,
    CodeModeResultKind,
    CodeModeResultSpec,
    CustomToolCallSummary,
    ToolApprovalScope,
    ToolContext,
)
from onyx.tools.tool_name import normalize_external_tool_name, sanitize_tool_name
from onyx.utils.logger import setup_logger

logger = setup_logger()

_AUTH_ERROR_INDICATORS = (
    "401",
    "unauthorized",
    "authentication",
    "forbidden",
    "access denied",
    "invalid token",
    "invalid api key",
    "invalid credentials",
    "please reconnect to the server",
)

# TODO: for now we're fitting MCP tool responses into the CustomToolCallSummary class
# In the future we may want custom handling for MCP tool responses
# class MCPToolCallSummary(BaseModel):
#     tool_name: str
#     server_url: str
#     tool_result: Any
#     server_name: str


def _reject_non_finite_number(constant: str) -> float:
    raise ValueError(f"Non-finite JSON number: {constant}")


def _tool_result_value(text: str) -> JsonValue:
    """The server's text, parsed when it is a JSON object or array, so the
    result is JSON-encoded once rather than as an escaped string inside JSON.
    Any other text, including a JSON scalar, stays a string."""
    try:
        parsed = json.loads(text, parse_constant=_reject_non_finite_number)
    except (ValueError, RecursionError):
        return text
    return parsed if isinstance(parsed, dict | list) else text


def _normalize_parameters_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    # Azure OpenAI rejects object schemas that omit `properties` with
    # "object schema missing properties". MCP servers (e.g. AWS Knowledge MCP's
    # aws___list_regions) may legally return `{"type": "object"}` with no
    # properties for zero-arg tools, so seed `properties: {}` ourselves.
    if not schema:
        return {"type": "object", "properties": {}}
    if schema.get("type", "object") == "object" and "properties" not in schema:
        return {**schema, "type": "object", "properties": {}}
    return schema


class MCPTool(Tool):
    """One tool of an MCP server integration. Each call resolves the
    credential of the acting user again, with the same check as
    construction (``resolve_call_credentials``)."""

    def __init__(
        self,
        *,
        integration_id: int,
        integration_name: str,
        server_url: str,
        transport: MCPTransport | None,
        tool_name: str,
        tool_description: str,
        tool_definition: dict[str, Any],
        acting_user_id: UUID | None,
        output_schema: dict[str, JsonValue] | None = None,
        additional_headers: dict[str, str] | None = None,
        approval: ToolApprovalScope | None = None,
    ) -> None:
        self.approval = approval
        self._integration_id = integration_id
        self._integration_name = integration_name
        self._server_url = server_url
        self._transport = transport
        self._acting_user_id = acting_user_id
        self._additional_headers = additional_headers or {}

        self._mcp_tool_name = tool_name
        self._name = normalize_external_tool_name(
            self.code_mode_function_name.qualified
        )
        self._tool_definition = tool_definition
        self._output_schema = output_schema
        self._description = tool_description
        self._display_name = tool_definition.get("displayName", tool_name)

    @property
    def id(self) -> int | None:
        # An integration action has no tool row.
        return None

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DEFERRED

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
    def code_mode_function_name(self) -> CodeModeFunctionName:
        return CodeModeFunctionName(
            name=self._mcp_tool_name,
            namespace=f"mcp__{self._integration_id}__{sanitize_tool_name(self._integration_name)}",
        )

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return CodeModeResultSpec(
            kind=CodeModeResultKind.MCP,
            output_schema=self._output_schema,
            returns=None
            if self._output_schema is not None
            else "The server's result. Structured content and JSON objects or "
            "arrays arrive parsed; other output arrives as a string. Print a small "
            "sample first if the shape is unknown.",
        )

    def tool_definition(self) -> ToolDefinition:
        """Return the tool definition from the MCP server"""
        return ToolDefinition(
            name=self._name,
            description=self._description,
            parameters=_normalize_parameters_schema(self._tool_definition),
        )

    def _error_result(self, message: JsonValue) -> ToolResult:
        error_result = {"error": message}
        return ToolResult(
            details=CustomToolCallSummary(
                tool_name=self._name, response_type="json", tool_result=error_result
            ),
            content=json.dumps(error_result),
            is_error=True,
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        """Check credentials, call the server, and report tool or authentication errors."""
        _start = time.monotonic()
        _server = self._integration_name
        outcome = MCPToolCallStatus.ERROR
        credentials: CallCredentials | None = None
        try:
            request_headers = {
                name: value
                for name, value in self._additional_headers.items()
                if name.lower() not in DENYLISTED_MCP_HEADERS
            }
            if denylisted := sorted(
                set(self._additional_headers) - set(request_headers)
            ):
                logger.warning(
                    "MCP tool '%s' received denylisted headers that were filtered: %s",
                    self._name,
                    denylisted,
                )
            resolved = resolve_call_credentials_by_id(
                self._integration_id, self._acting_user_id
            )
            if isinstance(resolved, ConnectionProblem):
                logger.warning(
                    "MCP tool '%s' cannot authenticate: %s",
                    self._name,
                    resolved.code.value,
                )
                outcome = MCPToolCallStatus.AUTH_ERROR
                return self._error_result(
                    f"The {self._name} tool from {self._integration_name} cannot "
                    f"run: {resolved.reason}"
                )
            credentials = resolved
            headers = merge_mcp_headers(request_headers, credentials.headers)

            tool_result = call_mcp_tool(
                self._server_url,
                self._mcp_tool_name,
                invocation.arguments,
                connection_headers=headers,
                transport=self._transport or MCPTransport.STREAMABLE_HTTP,
                auth=mcp_oauth_provider(credentials, self._transport),
                cancellation=invocation.cancellation,
            )

            if tool_result.isError:
                # A server-reported tool failure does not reject its credentials.
                message = _tool_result_value(process_mcp_result(tool_result))
                logger.info("MCP tool '%s' reported an error", self._name)
                return self._error_result(message)

            logger.info("MCP tool '%s' executed successfully", self._name)

            tool_result_dict = {
                "tool_result": _tool_result_value(process_mcp_result(tool_result))
            }
            response = ToolResult(
                details=CustomToolCallSummary(
                    tool_name=self._name,
                    response_type="json",
                    tool_result=tool_result_dict,
                    structured_result=tool_result.structuredContent,
                ),
                content=json.dumps(tool_result_dict),
            )
            outcome = MCPToolCallStatus.SUCCESS
            return response

        except AgentCancelled:
            outcome = MCPToolCallStatus.CANCELLED
            raise
        except Exception as e:
            unauthorized_response = has_unauthorized_response(e)
            if unauthorized_response and credentials is not None:
                try:
                    mark_api_key_rejected(credentials)
                except Exception:
                    logger.exception("Could not record rejected MCP credentials")
            error_str = str(e).lower()
            logger.error("Failed to execute MCP tool '%s': %s", self._name, e)

            is_auth_error = (
                unauthorized_response
                or isinstance(e, MCPReauthenticationRequired)
                or any(indicator in error_str for indicator in _AUTH_ERROR_INDICATORS)
            )

            if is_auth_error:
                outcome = MCPToolCallStatus.AUTH_ERROR
                return self._error_result(
                    f"Authentication failed for the {self._name} tool from "
                    f"{self._integration_name}. Reconnect {self._integration_name} "
                    f"from the Plugins page. Original error: {str(e)}"
                )
            return self._error_result(f"Tool execution failed: {str(e)}")
        finally:
            record_mcp_client_tool_outcome(
                server_name=_server,
                tool_name=self._name,
                start_time=_start,
                status=outcome,
            )
