"""
MCP (Model Context Protocol) Client Implementation

This module provides a proper MCP client that follows the JSON-RPC 2.0 specification
and handles connection initialization, session management, and protocol communication.
"""

from collections.abc import Awaitable
from collections.abc import Callable
from enum import Enum
from typing import Any
from typing import Dict
from typing import TypeVar
from urllib.parse import urlencode

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client  # or use stdio_client
from mcp.types import CallToolResult
from mcp.types import InitializeResult
from mcp.types import ListResourcesResult
from mcp.types import TextResourceContents
from mcp.types import Tool as MCPLibTool
from pydantic import BaseModel

from onyx.db.enums import MCPTransport
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel

logger = setup_logger()

T = TypeVar("T", covariant=True)

MCPClientFunction = Callable[[ClientSession], Awaitable[T]]


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
#         transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
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


def _create_mcp_client_function_runner(
    function: Callable[[ClientSession], Awaitable[T]],
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    auth: OAuthClientProvider | None = None,  # TODO: maybe used this for all auth types
    **kwargs: Any,
) -> Callable[[], Awaitable[T]]:
    auth_headers = connection_headers or {}
    # Normalize URL
    normalized_url = server_url.rstrip("/")
    # WARNING: httpx.Auth with requires_response_body=True (as in the MCP OAuth
    # provider) forces httpx to fully read the response body. That is incompatible
    # with SSE (infinite stream). Avoid passing auth for SSE; rely on headers.
    auth_for_request = None
    if transport == MCPTransport.STREAMABLE_HTTP:
        # Only append transportType for Streamable HTTP; SSE endpoints typically do not
        # expect this parameter and some servers may misbehave when it is present.
        sep = "?" if "?" not in normalized_url else "&"
        server_url = (
            normalized_url
            + sep
            + urlencode({"transportType": transport.value.lower().replace("_", "-")})
        )
        auth_for_request = auth
    else:
        server_url = normalized_url

    # doing this here for mypy
    client_func = (
        streamablehttp_client
        if transport == MCPTransport.STREAMABLE_HTTP
        else sse_client
    )

    async def run_client_function() -> T:
        async with client_func(
            server_url, headers=auth_headers, auth=auth_for_request
        ) as client_tuple:
            if len(client_tuple) == 3:
                read, write, _ = client_tuple
            elif len(client_tuple) == 2:
                assert isinstance(client_tuple, tuple)  # mypy
                read, write = client_tuple
            else:
                raise ValueError(
                    f"Unexpected number of client tuple elements: {len(client_tuple)}"
                )
            from datetime import timedelta

            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=300)
            ) as session:
                return await function(session, **kwargs)

    return run_client_function


def log_exception_group(e: ExceptionGroup) -> Exception | None:
    logger.error(e)
    saved_e = None
    for err in e.exceptions:
        if isinstance(err, ExceptionGroup):
            saved_e = log_exception_group(err) or saved_e
        else:
            logger.error(err)
            saved_e = err

    return saved_e


def _call_mcp_client_function_sync(
    function: Callable[[ClientSession], Awaitable[T]],
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    auth: OAuthClientProvider | None = None,
    **kwargs: Any,
) -> T:
    run_client_function = _create_mcp_client_function_runner(
        function, server_url, connection_headers, transport, auth, **kwargs
    )
    try:
        return run_async_sync_no_cancel(run_client_function())
    except Exception as e:
        logger.error(f"Failed to call MCP client function: {e}")
        if isinstance(e, ExceptionGroup):
            original_exception = e
            saved_e = log_exception_group(e)
            if saved_e:
                raise saved_e
            raise original_exception
        raise e


async def _call_mcp_client_function_async(
    function: Callable[[ClientSession], Awaitable[T]],
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    auth: OAuthClientProvider | None = None,
    **kwargs: Any,
) -> T:
    run_client_function = _create_mcp_client_function_runner(
        function, server_url, connection_headers, transport, auth, **kwargs
    )
    return await run_client_function()


def process_mcp_result(call_tool_result: CallToolResult) -> str:
    """Flatten MCP CallToolResult->text (prefers text content blocks)."""
    # TODO: use structured_content if available
    parts = []
    for content_block in call_tool_result.content:
        if content_block.type == ContentBlockTypes.TEXT.value:
            parts.append(content_block.text or "")
        if content_block.type == ContentBlockTypes.RESOURCE.value:
            if isinstance(content_block.resource, TextResourceContents):
                parts.append(content_block.resource.text or "")
            # TODO: handle blob resource content
        if content_block.type == ContentBlockTypes.RESOURCE_LINK.value:
            parts.append(
                f"link: {content_block.uri} title: {content_block.title} description: {content_block.description}"
            )
        # TODO: handle other content block types

    return "\n\n".join(p for p in parts if p) or str(call_tool_result.structuredContent)


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
    connection_headers: dict[str, str] | None = None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    auth: OAuthClientProvider | None = None,
) -> str:
    """Call a specific tool on the MCP server"""
    return _call_mcp_client_function_sync(
        _call_mcp_tool(tool_name, arguments),
        server_url,
        connection_headers,
        transport,
        auth,
    )


async def initialize_mcp_client(
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    auth: OAuthClientProvider | None = None,
) -> InitializeResult:
    return await _call_mcp_client_function_async(
        lambda session: session.initialize(),
        server_url,
        connection_headers,
        transport,
        auth,
    )


async def _discover_mcp_tools(session: ClientSession) -> list[MCPLibTool]:
    # 1) initialize
    import time

    t1 = time.time()
    init_result = await session.initialize()  # sends JSON-RPC "initialize"
    logger.info(f"Initialized with server: {init_result.serverInfo}")
    logger.info(f"Initialized with server time: {time.time() - t1}")
    # 2) tools/list
    t2 = time.time()
    tools_response = await session.list_tools()  # sends JSON-RPC "tools/list"
    logger.info(f"Listed tools with server time: {time.time() - t2}")
    return tools_response.tools


def discover_mcp_tools(
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    auth: OAuthClientProvider | None = None,
) -> list[MCPLibTool]:
    """
    Synchronous wrapper for discovering MCP tools.
    """
    return _call_mcp_client_function_sync(
        _discover_mcp_tools,
        server_url,
        connection_headers,
        transport,
        auth,
    )


async def _discover_mcp_resources(session: ClientSession) -> ListResourcesResult:
    return await session.list_resources()


def discover_mcp_resources_sync(
    server_url: str,
    connection_headers: dict[str, str] | None = None,
    transport: str = "streamable-http",
    auth: OAuthClientProvider | None = None,
) -> ListResourcesResult:
    """
    Synchronous wrapper for discovering MCP resources.
    This is for compatibility with the existing codebase.
    """
    return _call_mcp_client_function_sync(
        _discover_mcp_resources,
        server_url,
        connection_headers,
        MCPTransport(transport),
        auth,
    )
