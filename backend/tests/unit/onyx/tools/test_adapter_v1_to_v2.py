import uuid
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.models import MCPServer
from onyx.tools.adapter_v1_to_v2 import tool_to_function_tool
from onyx.tools.adapter_v1_to_v2 import tools_to_function_tools
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


class MockEmitter:
    """Mock emitter that tracks packet history for testing."""

    def __init__(self):
        self.packet_history: list = []

    def emit(self, packet):
        """Emit a packet and add it to history."""
        self.packet_history.append(packet)


@pytest.fixture
def openapi_schema() -> dict[str, Any]:
    """OpenAPI schema for testing."""
    return {
        "openapi": "3.0.0",
        "info": {
            "version": "1.0.0",
            "title": "Test API",
            "description": "A test API for adapter testing",
        },
        "servers": [
            {"url": "http://localhost:8080/CHAT_SESSION_ID/test/MESSAGE_ID"},
        ],
        "paths": {
            "/test/{test_id}": {
                "GET": {
                    "summary": "Get a test item",
                    "operationId": "getTestItem",
                    "parameters": [
                        {
                            "name": "test_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                },
                "POST": {
                    "summary": "Create a test item",
                    "operationId": "createTestItem",
                    "parameters": [
                        {
                            "name": "test_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                },
            }
        },
    }


@pytest.fixture
def dynamic_schema_info() -> DynamicSchemaInfo:
    """Dynamic schema info for testing."""
    return DynamicSchemaInfo(chat_session_id=uuid.uuid4(), message_id=42)


@pytest.fixture
def mcp_server() -> MCPServer:
    """MCP server for testing."""
    return MCPServer(
        id=1,
        name="test_mcp_server",
        server_url="http://localhost:8080/mcp",
        auth_type=MCPAuthenticationType.NONE,
        transport=MCPTransport.STREAMABLE_HTTP,
    )


@pytest.fixture
def mcp_tool(mcp_server: MCPServer) -> MCPTool:
    """MCP tool for testing."""
    tool_definition = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The search query"}},
        "required": ["query"],
    }

    return MCPTool(
        tool_id=1,
        mcp_server=mcp_server,
        tool_name="search",
        tool_description="Search for information",
        tool_definition=tool_definition,
        connection_config=None,
        user_email="test@example.com",
    )


@pytest.fixture
def image_generation_tool() -> ImageGenerationTool:
    """Image generation tool for testing."""
    return ImageGenerationTool(
        api_key="test-api-key",
        api_base=None,
        api_version=None,
        tool_id=3,
        model="test-model",
        num_imgs=1,
    )


@pytest.fixture
def web_search_tool() -> WebSearchTool:
    """Web search tool for testing."""
    return WebSearchTool(tool_id=4)


@pytest.fixture
def okta_profile_tool() -> OktaProfileTool:
    """Okta profile tool for testing."""
    return OktaProfileTool(
        access_token="test-access-token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        openid_config_url="https://test.okta.com/.well-known/openid_configuration",
        okta_api_token="test-api-token",
        tool_id=5,
    )


def test_tool_to_function_tool_post_method(
    openapi_schema: dict[str, Any], dynamic_schema_info: DynamicSchemaInfo
) -> None:
    """
    Test conversion of a POST method tool.
    Verifies that the adapter works with different HTTP methods.
    """
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=-1,  # dummy tool id
        openapi_schema=openapi_schema,
        dynamic_schema_info=dynamic_schema_info,
    )

    # Get the second tool (POST method)
    v1_tool = tools[1]
    v2_tool = tool_to_function_tool(v1_tool)

    # Verify the conversion works for POST method
    assert v2_tool.name == v1_tool.name
    assert v2_tool.description == v1_tool.description
    assert (
        v2_tool.params_json_schema
        == v1_tool.tool_definition()["function"]["parameters"]
    )
    assert v2_tool.on_invoke_tool is not None


@patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
def test_custom_tool_invocation(
    mock_request: MagicMock,
    openapi_schema: dict[str, Any],
    dynamic_schema_info: DynamicSchemaInfo,
) -> None:
    """
    Test that the converted FunctionTool can be invoked correctly.
    Verifies that the on_invoke_tool method works as expected and emits packets.
    """
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=-1,  # dummy tool id
        openapi_schema=openapi_schema,
        dynamic_schema_info=dynamic_schema_info,
    )

    v1_tool = tools[0]
    v2_tool = tool_to_function_tool(v1_tool)

    # Create a mock emitter that tracks packet history
    mock_emitter = MockEmitter()

    # Mock the tool context with an unmocked emitter
    mock_context = MagicMock()
    mock_context.context = MagicMock()
    mock_context.context.run_dependencies = MagicMock()
    mock_context.context.run_dependencies.emitter = mock_emitter
    mock_context.context.current_run_step = 0

    # Test the on_invoke_tool method
    # The FunctionTool expects a JSON string as input
    test_args = '{"test_id": "123"}'

    # This should call the original tool's run method
    # We need to handle the async nature of the FunctionTool
    import asyncio

    async def test_invoke():
        return await v2_tool.on_invoke_tool(mock_context, test_args)

    # Run the async function
    result = asyncio.run(test_invoke())

    # Verify the tool was called with the correct arguments
    expected_url = f"http://localhost:8080/{dynamic_schema_info.chat_session_id}/test/{dynamic_schema_info.message_id}/test/123"
    mock_request.assert_called_once_with("GET", expected_url, json=None, headers={})

    # The result should be a list of ToolResponse objects
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].id == "custom_tool_response"

    assert len(mock_emitter.packet_history) == 3

    start_packet = mock_emitter.packet_history[0]
    delta_packet = mock_emitter.packet_history[1]
    section_end_packet = mock_emitter.packet_history[2]

    assert getattr(start_packet.obj, "type", None) == "custom_tool_start"
    assert getattr(delta_packet.obj, "type", None) == "custom_tool_delta"
    assert getattr(section_end_packet.obj, "type", None) == "section_end"


def test_tool_to_function_tool_mcp_tool(mcp_tool: MCPTool) -> None:
    """
    Test conversion of an MCP tool to FunctionTool.
    Verifies that the adapter works with MCP tools.
    """
    v2_tool = tool_to_function_tool(mcp_tool)

    # Verify the conversion works for MCP tool
    assert v2_tool.name == mcp_tool.name
    assert v2_tool.description == mcp_tool.description
    assert (
        v2_tool.params_json_schema
        == mcp_tool.tool_definition()["function"]["parameters"]
    )
    assert v2_tool.on_invoke_tool is not None


@patch("onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool")
def test_mcp_tool_invocation(mock_call_mcp_tool: MagicMock, mcp_tool: MCPTool) -> None:
    """
    Test that the converted MCP FunctionTool can be invoked correctly.
    Verifies that the on_invoke_tool method works as expected for MCP tools and emits packets.
    """
    # Mock the MCP tool call response
    mock_call_mcp_tool.return_value = "Search results: test query"

    v2_tool = tool_to_function_tool(mcp_tool)

    # Create a mock emitter that tracks packet history
    mock_emitter = MockEmitter()

    # Mock the tool context with an unmocked emitter
    mock_context = MagicMock()
    mock_context.context = MagicMock()
    mock_context.context.run_dependencies = MagicMock()
    mock_context.context.run_dependencies.emitter = mock_emitter
    mock_context.context.current_run_step = 0

    # Test the on_invoke_tool method
    # The FunctionTool expects a JSON string as input
    test_args = '{"query": "test search"}'

    # This should call the original tool's run method
    # We need to handle the async nature of the FunctionTool
    import asyncio

    async def test_invoke():
        return await v2_tool.on_invoke_tool(mock_context, test_args)

    # Run the async function
    result = asyncio.run(test_invoke())

    # Verify the MCP tool was called with the correct arguments
    mock_call_mcp_tool.assert_called_once_with(
        mcp_tool.mcp_server.server_url,
        mcp_tool.name,
        {"query": "test search"},
        connection_headers={},
        transport=mcp_tool.mcp_server.transport,
    )

    # The result should be a list of ToolResponse objects
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].id == "custom_tool_response"

    assert len(mock_emitter.packet_history) == 3

    start_packet = mock_emitter.packet_history[0]
    delta_packet = mock_emitter.packet_history[1]
    section_end_packet = mock_emitter.packet_history[2]

    assert getattr(start_packet.obj, "type", None) == "custom_tool_start"
    assert getattr(delta_packet.obj, "type", None) == "custom_tool_delta"
    assert getattr(section_end_packet.obj, "type", None) == "section_end"


def test_tools_to_function_tools_comprehensive(
    openapi_schema: dict[str, Any],
    dynamic_schema_info: DynamicSchemaInfo,
    mcp_tool: MCPTool,
    image_generation_tool: ImageGenerationTool,
    web_search_tool: WebSearchTool,
    okta_profile_tool: OktaProfileTool,
) -> None:
    """
    Test conversion of a mixed list of tools to FunctionTools.
    Verifies that the adapter correctly handles:
    - MCP tools (converted via tool_to_function_tool)
    - Custom tools (converted via tool_to_function_tool)
    - Built-in tools (ImageGenerationTool, WebSearchTool, OktaProfileTool)
      (converted via BUILT_IN_TOOL_MAP_V2)
    """
    # Create custom tools from the OpenAPI schema
    custom_tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=-1,  # dummy tool id
        openapi_schema=openapi_schema,
        dynamic_schema_info=dynamic_schema_info,
    )

    # Create a mixed list of different tool types
    mixed_tools = [
        mcp_tool,  # MCP tool
        custom_tools[0],  # Custom tool (GET method)
        image_generation_tool,  # Built-in image generation tool
        web_search_tool,  # Built-in web search tool
        okta_profile_tool,  # Built-in okta profile tool
    ]

    # Convert the tools
    function_tools = tools_to_function_tools(mixed_tools)

    # Verify we got a list of FunctionTools
    assert isinstance(function_tools, list)
    assert len(function_tools) > 0
    assert all(
        hasattr(tool, "name")
        and hasattr(tool, "description")
        and hasattr(tool, "on_invoke_tool")
        for tool in function_tools
    )

    # Verify that built-in tools are mapped to their V2 equivalents
    # ImageGenerationTool should map to image_generation_tool
    image_function_tools = [
        tool for tool in function_tools if tool.name == "image_generation_tool"
    ]
    assert len(image_function_tools) == 1

    # WebSearchTool should map to web_search_tool and web_fetch_tool (2 tools)
    web_function_tools = [
        tool
        for tool in function_tools
        if tool.name in ["web_search_tool", "web_fetch_tool"]
    ]
    assert len(web_function_tools) == 2

    # OktaProfileTool should map to okta_profile_tool
    okta_function_tools = [
        tool for tool in function_tools if tool.name == "okta_profile_tool"
    ]
    assert len(okta_function_tools) == 1

    # Verify that custom and MCP tools are converted via tool_to_function_tool
    # These should have the same names as their original tools
    mcp_function_tools = [tool for tool in function_tools if tool.name == mcp_tool.name]
    assert len(mcp_function_tools) == 1

    custom_function_tools = [
        tool for tool in function_tools if tool.name == custom_tools[0].name
    ]
    assert len(custom_function_tools) == 1

    # Verify that all FunctionTools have the required properties
    for tool in function_tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "params_json_schema")
        assert hasattr(tool, "on_invoke_tool")
        assert tool.name is not None
        assert tool.description is not None
        assert tool.on_invoke_tool is not None
