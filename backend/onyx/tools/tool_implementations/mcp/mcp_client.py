"""
MCP (Model Context Protocol) Client Implementation

This module provides a proper MCP client that follows the JSON-RPC 2.0 specification
and handles connection initialization, session management, and protocol communication.
"""

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from enum import Enum
from typing import Any
from typing import Dict
from typing import TypeVar
from urllib.parse import urlencode

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client  # or use stdio_client
from mcp.types import CallToolResult
from mcp.types import InitializeResult
from mcp.types import ListResourcesResult
from mcp.types import Tool as MCPLibTool
from pydantic import BaseModel

from onyx.utils.logger import setup_logger

logger = setup_logger()

T = TypeVar("T", covariant=True)

MCPClientFunction = Callable[[ClientSession], Awaitable[T]]


class MCPTransport(str, Enum):
    """MCP transport types"""

    STDIO = "stdio"
    SSE = "sse"  # Server-Sent Events (deprecated but still used)
    HTTP_STREAM = "streamable-http"  # Modern HTTP streaming


class MCPMessageType(str, Enum):
    """MCP message types"""

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


class ContentBlockTypes(str, Enum):
    """MCP content block types"""  # Unfortunstely these aren't exposed by the mcp library

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    RESOURCE = "resource"
    RESOURCE_LINK = "resource_link"


class MCPMessage(BaseModel):
    """Base MCP message following JSON-RPC 2.0"""

    jsonrpc: str = "2.0"
    method: str | None = None
    params: Dict[str, Any] | None = None
    id: Any | None = None
    result: Any | None = None
    error: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-RPC message dict"""
        msg: Dict[str, Any] = {"jsonrpc": self.jsonrpc}

        if self.id is not None:
            msg["id"] = self.id

        if self.method is not None:
            msg["method"] = self.method

        if self.params is not None:
            msg["params"] = self.params

        if self.result is not None:
            msg["result"] = self.result

        if self.error is not None:
            msg["error"] = self.error

        return msg


# TODO: in the future we should do things like manage sessions and handle errors better
# using an abstraction like this. For now things are purely functional and we initialize
# a new session for each tool call.
# class MCPClient:
#     """
#     MCP Client implementation that properly handles the protocol lifecycle
#     and different transport mechanisms.
#     """

#     def __init__(
#         self,
#         server_url: str,
#         transport: MCPTransport = MCPTransport.HTTP_STREAM,
#         auth_token: str | None = None,
#     ):
#         self.server_url = server_url
#         self.transport = transport
#         self.auth_token = auth_token

#         # Session management
#         self.session: Optional[aiohttp.ClientSession] = None
#         self.initialized = False
#         self.capabilities: Dict[str, Any] = {}
#         self.protocol_version = "2025-03-26"  # Current MCP protocol version
#         self.session_id: str | None = None
#         # Legacy HTTP+SSE transport support (backwards compatibility)
#         self.legacy_post_endpoint: str | None = None

#         # Message ID counter
#         self._message_id_counter = 0

#         # For stdio transport
#         self.process: Optional[subprocess.Popen] = None


def _call_mcp_client_function(
    function: Callable[[ClientSession], Awaitable[T]],
    server_url: str,
    connection_headers: dict[str, Any] | None = None,
    transport: MCPTransport = MCPTransport.HTTP_STREAM,
    **kwargs: Any,
) -> T:
    auth_headers = connection_headers or {}
    server_url = (
        server_url.rstrip("/") + "?" + urlencode({"transportType": transport.value})
    )

    async def run_client_function() -> T:
        async with streamablehttp_client(server_url, headers=auth_headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                return await function(session, **kwargs)

    try:
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_client_function())
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Failed to call MCP client function: {e}")
        if isinstance(e, ExceptionGroup):
            err = e
            for err in e.exceptions:
                logger.error(err)
            raise err
        raise e


def process_mcp_result(call_tool_result: CallToolResult) -> str:
    """Flatten MCP CallToolResult->text (prefers text content blocks)."""
    # TODO: use structured_content if available
    parts = []
    for content_block in call_tool_result.content:
        if content_block.type == ContentBlockTypes.TEXT.value:
            parts.append(content_block.text or "")
        # TODO: handle other content block types

    return "\n".join(p for p in parts if p) or str(call_tool_result.structuredContent)


def _call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> MCPClientFunction[str]:
    async def call_tool(session: ClientSession) -> str:
        await session.initialize()
        result = await session.call_tool(tool_name, arguments)
        return process_mcp_result(result)

    return call_tool


def call_mcp_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    connection_headers: dict[str, Any] | None = None,
    transport: str = "streamable-http",
) -> str:
    """Call a specific tool on the MCP server"""
    return _call_mcp_client_function(
        _call_mcp_tool(tool_name, arguments),
        server_url,
        connection_headers,
        MCPTransport(transport),
    )


def initialize_mcp_client(
    server_url: str,
    connection_headers: dict[str, Any] | None = None,
    transport: str = "streamable-http",
) -> InitializeResult:
    return _call_mcp_client_function(
        lambda session: session.initialize(),
        server_url,
        connection_headers,
        MCPTransport(transport),
    )


async def _discover_mcp_tools(session: ClientSession) -> list[MCPLibTool]:
    # 1) initialize
    init_result = await session.initialize()  # sends JSON-RPC "initialize"
    logger.info(f"Initialized with server: {init_result.serverInfo}")

    # 2) tools/list
    tools_response = await session.list_tools()  # sends JSON-RPC "tools/list"
    return tools_response.tools


def discover_mcp_tools(
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: str = "streamable-http",
) -> list[MCPLibTool]:
    """
    Synchronous wrapper for discovering MCP tools.
    """
    return _call_mcp_client_function(
        _discover_mcp_tools,
        server_url,
        connection_headers,
        MCPTransport(transport),
    )


async def _discover_mcp_resources(session: ClientSession) -> ListResourcesResult:
    return await session.list_resources()


def discover_mcp_resources_sync(
    server_url: str,
    connection_headers: dict[str, Any] | None = None,
    transport: str = "streamable-http",
) -> ListResourcesResult:
    """
    Synchronous wrapper for discovering MCP resources.
    This is for compatibility with the existing codebase.
    """
    return _call_mcp_client_function(
        _discover_mcp_resources,
        server_url,
        connection_headers,
        MCPTransport(transport),
    )
