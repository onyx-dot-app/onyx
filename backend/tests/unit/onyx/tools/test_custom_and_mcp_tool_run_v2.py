"""Tests for CustomTool and MCPTool run_v2() methods using dependency injection.

This test module focuses on testing the run_v2() methods for CustomTool and MCPTool,
adapted from test_adapter_v1_to_v2.py but directly testing the tool implementations.
"""

import json
import uuid
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.models import ChatTurnContext
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.models import MCPServer
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from tests.unit.onyx.chat.turn.utils import FakeRedis


# =============================================================================
# Fake Classes for Dependency Injection
# =============================================================================


def create_fake_database_session() -> Any:
    """Create a fake SQLAlchemy Session for testing"""
    from unittest.mock import Mock
    from sqlalchemy.orm import Session

    fake_session = Mock(spec=Session)
    fake_session.committed = False
    fake_session.rolled_back = False

    def mock_commit() -> None:
        fake_session.committed = True

    def mock_rollback() -> None:
        fake_session.rolled_back = True

    fake_session.commit = mock_commit
    fake_session.rollback = mock_rollback
    fake_session.add = Mock()
    fake_session.flush = Mock()

    return fake_session


class FakeEmitter:
    """Fake emitter for testing that records all emitted packets"""

    def __init__(self) -> None:
        self.packet_history: list[Any] = []

    def emit(self, packet: Any) -> None:
        self.packet_history.append(packet)


class FakeRunDependencies:
    """Fake run dependencies for testing"""

    def __init__(self, db_session: Any, redis_client: FakeRedis, tool: Any) -> None:
        self.db_session = db_session
        self.redis_client = redis_client
        self.emitter = FakeEmitter()
        self.tools = [tool]


# =============================================================================
# Test Helper Functions
# =============================================================================


def create_fake_run_context(
    chat_session_id: UUID,
    message_id: int,
    db_session: Any,
    redis_client: FakeRedis,
    tool: Any,
    current_run_step: int = 0,
) -> RunContextWrapper[ChatTurnContext]:
    """Create a fake run context for testing"""
    run_dependencies = FakeRunDependencies(db_session, redis_client, tool)

    context = ChatTurnContext(
        chat_session_id=chat_session_id,
        message_id=message_id,
        run_dependencies=run_dependencies,  # type: ignore
    )
    context.current_run_step = current_run_step

    return RunContextWrapper(context=context)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def chat_session_id() -> UUID:
    """Fixture providing fake chat session ID."""
    return uuid.uuid4()


@pytest.fixture
def message_id() -> int:
    """Fixture providing fake message ID."""
    return 123


@pytest.fixture
def fake_db_session() -> Any:
    """Fixture providing a fake database session."""
    return create_fake_database_session()


@pytest.fixture
def fake_redis_client() -> FakeRedis:
    """Fixture providing a fake Redis client."""
    return FakeRedis()


@pytest.fixture
def openapi_schema() -> dict[str, Any]:
    """OpenAPI schema for testing."""
    return {
        "openapi": "3.0.0",
        "info": {
            "version": "1.0.0",
            "title": "Test API",
            "description": "A test API for testing",
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
            }
        },
    }


@pytest.fixture
def dynamic_schema_info(chat_session_id: UUID, message_id: int) -> DynamicSchemaInfo:
    """Dynamic schema info for testing."""
    return DynamicSchemaInfo(chat_session_id=chat_session_id, message_id=message_id)


@pytest.fixture
def custom_tool(
    openapi_schema: dict[str, Any], dynamic_schema_info: DynamicSchemaInfo
) -> CustomTool:
    """Custom tool for testing."""
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=-1,  # dummy tool id
        openapi_schema=openapi_schema,
        dynamic_schema_info=dynamic_schema_info,
    )
    return tools[0]


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


# =============================================================================
# Custom Tool Tests
# =============================================================================


@patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
def test_custom_tool_run_v2_basic_invocation(
    mock_request: MagicMock,
    custom_tool: CustomTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
    dynamic_schema_info: DynamicSchemaInfo,
) -> None:
    """Test basic functionality of CustomTool.run_v2()."""
    # Arrange
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.json.return_value = {
        "id": "456",
        "name": "Test Item",
        "status": "active",
    }
    mock_request.return_value = mock_response

    fake_run_context = create_fake_run_context(
        chat_session_id, message_id, fake_db_session, fake_redis_client, custom_tool
    )

    # Act
    result = custom_tool.run_v2(fake_run_context, test_id="456")

    # Assert
    assert isinstance(result, str)
    result_json = json.loads(result)
    assert result_json["id"] == "456"
    assert result_json["name"] == "Test Item"
    assert result_json["status"] == "active"

    # Verify HTTP request was made
    expected_url = f"http://localhost:8080/{dynamic_schema_info.chat_session_id}/test/{dynamic_schema_info.message_id}/test/456"
    mock_request.assert_called_once_with("GET", expected_url, json=None, headers={})


@patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
def test_custom_tool_run_v2_iteration_tracking(
    mock_request: MagicMock,
    custom_tool: CustomTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
) -> None:
    """Test that IterationInstructions and IterationAnswer are properly added."""
    # Arrange
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.json.return_value = {"result": "success"}
    mock_request.return_value = mock_response

    fake_run_context = create_fake_run_context(
        chat_session_id, message_id, fake_db_session, fake_redis_client, custom_tool
    )

    # Act
    custom_tool.run_v2(fake_run_context, test_id="789")

    # Assert - verify IterationInstructions was added
    assert len(fake_run_context.context.iteration_instructions) == 1
    iteration_instruction = fake_run_context.context.iteration_instructions[0]
    assert isinstance(iteration_instruction, IterationInstructions)
    assert iteration_instruction.iteration_nr == 1
    assert iteration_instruction.plan == f"Running {custom_tool.name}"
    assert iteration_instruction.purpose == f"Running {custom_tool.name}"
    assert iteration_instruction.reasoning == f"Running {custom_tool.name}"

    # Assert - verify IterationAnswer was added
    assert len(fake_run_context.context.global_iteration_responses) == 1
    iteration_answer = fake_run_context.context.global_iteration_responses[0]
    assert isinstance(iteration_answer, IterationAnswer)
    assert iteration_answer.tool == custom_tool.name
    assert iteration_answer.tool_id == custom_tool.id
    assert iteration_answer.iteration_nr == 1
    assert iteration_answer.parallelization_nr == 0
    assert iteration_answer.question == '{"test_id": "789"}'
    assert iteration_answer.reasoning == f"Running {custom_tool.name}"
    assert iteration_answer.answer == "{'result': 'success'}"
    assert iteration_answer.cited_documents == {}


@patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
def test_custom_tool_run_v2_packet_emissions(
    mock_request: MagicMock,
    custom_tool: CustomTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
) -> None:
    """Test that the correct packets are emitted during tool execution."""
    # Arrange
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.json.return_value = {"test": "data"}
    mock_request.return_value = mock_response

    fake_run_context = create_fake_run_context(
        chat_session_id, message_id, fake_db_session, fake_redis_client, custom_tool
    )

    # Act
    custom_tool.run_v2(fake_run_context, test_id="123")

    # Assert - verify emitter captured packets
    emitter = fake_run_context.context.run_dependencies.emitter
    # Should have: CustomToolStart, CustomToolDelta
    assert len(emitter.packet_history) >= 2

    # Check CustomToolStart
    start_packet = emitter.packet_history[0]
    assert getattr(start_packet.obj, "type", None) == "custom_tool_start"
    assert start_packet.obj.tool_name == custom_tool.name

    # Check CustomToolDelta
    delta_packet = emitter.packet_history[1]
    assert getattr(delta_packet.obj, "type", None) == "custom_tool_delta"
    assert delta_packet.obj.tool_name == custom_tool.name


@patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
@patch("onyx.tools.tool_implementations.custom.custom_tool.get_default_file_store")
@patch("uuid.uuid4")
def test_custom_tool_run_v2_csv_response_with_file_ids(
    mock_uuid: MagicMock,
    mock_file_store: MagicMock,
    mock_request: MagicMock,
    custom_tool: CustomTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
) -> None:
    """Test that CSV responses with file_ids are handled correctly."""
    # Arrange
    mock_uuid.return_value = uuid.UUID("12345678-1234-5678-9abc-123456789012")
    mock_store_instance = MagicMock()
    mock_file_store.return_value = mock_store_instance
    mock_store_instance.save_file.return_value = "csv_file_123"

    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "text/csv"}
    mock_response.content = b"name,age,city\nJohn,30,New York\nJane,25,Los Angeles"
    mock_request.return_value = mock_response

    fake_run_context = create_fake_run_context(
        chat_session_id,
        message_id,
        fake_db_session,
        fake_redis_client,
        custom_tool,
        current_run_step=2,
    )

    # Act
    result = custom_tool.run_v2(fake_run_context, test_id="789")

    # Assert - verify result contains file_ids
    result_json = json.loads(result)
    assert "file_ids" in result_json
    assert result_json["file_ids"] == ["12345678-1234-5678-9abc-123456789012"]

    # Assert - verify IterationAnswer has correct file_ids
    assert len(fake_run_context.context.global_iteration_responses) == 1
    iteration_answer = fake_run_context.context.global_iteration_responses[0]
    assert iteration_answer.data is None
    assert iteration_answer.file_ids == ["12345678-1234-5678-9abc-123456789012"]
    assert iteration_answer.response_type == "csv"

    # Verify file was saved
    mock_store_instance.save_file.assert_called_once()


# =============================================================================
# MCP Tool Tests
# =============================================================================


@patch("onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool")
def test_mcp_tool_run_v2_basic_invocation(
    mock_call_mcp_tool: MagicMock,
    mcp_tool: MCPTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
) -> None:
    """Test basic functionality of MCPTool.run_v2()."""
    # Arrange
    mock_call_mcp_tool.return_value = "MCP search results: test query"

    fake_run_context = create_fake_run_context(
        chat_session_id, message_id, fake_db_session, fake_redis_client, mcp_tool
    )

    # Act
    result = mcp_tool.run_v2(fake_run_context, query="test search")

    # Assert
    assert isinstance(result, str)
    # The result is already a JSON string containing {"tool_result": ...}
    result_json = json.loads(result)
    # The tool_result is itself a JSON string that needs to be parsed
    inner_result = json.loads(result_json)
    assert "tool_result" in inner_result
    assert inner_result["tool_result"] == "MCP search results: test query"

    # Verify MCP tool was called
    mock_call_mcp_tool.assert_called_once_with(
        mcp_tool.mcp_server.server_url,
        mcp_tool.name,
        {"query": "test search"},
        connection_headers={},
        transport=mcp_tool.mcp_server.transport,
    )


@patch("onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool")
def test_mcp_tool_run_v2_iteration_tracking(
    mock_call_mcp_tool: MagicMock,
    mcp_tool: MCPTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
) -> None:
    """Test that IterationInstructions and IterationAnswer are properly added."""
    # Arrange
    mock_call_mcp_tool.return_value = "MCP search results"

    fake_run_context = create_fake_run_context(
        chat_session_id,
        message_id,
        fake_db_session,
        fake_redis_client,
        mcp_tool,
        current_run_step=1,
    )

    # Act
    mcp_tool.run_v2(fake_run_context, query="test mcp search")

    # Assert - verify IterationInstructions was added
    assert len(fake_run_context.context.iteration_instructions) == 1
    iteration_instruction = fake_run_context.context.iteration_instructions[0]
    assert isinstance(iteration_instruction, IterationInstructions)
    assert iteration_instruction.iteration_nr == 2
    assert iteration_instruction.plan == f"Running {mcp_tool.name}"
    assert iteration_instruction.purpose == f"Running {mcp_tool.name}"
    assert iteration_instruction.reasoning == f"Running {mcp_tool.name}"

    # Assert - verify IterationAnswer was added
    assert len(fake_run_context.context.global_iteration_responses) == 1
    iteration_answer = fake_run_context.context.global_iteration_responses[0]
    assert isinstance(iteration_answer, IterationAnswer)
    assert iteration_answer.tool == mcp_tool.name
    assert iteration_answer.tool_id == mcp_tool.id
    assert iteration_answer.iteration_nr == 2
    assert iteration_answer.parallelization_nr == 0
    assert iteration_answer.question == '{"query": "test mcp search"}'
    assert iteration_answer.reasoning == f"Running {mcp_tool.name}"
    assert iteration_answer.cited_documents == {}


@patch("onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool")
def test_mcp_tool_run_v2_packet_emissions(
    mock_call_mcp_tool: MagicMock,
    mcp_tool: MCPTool,
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
) -> None:
    """Test that the correct packets are emitted during MCP tool execution."""
    # Arrange
    mock_call_mcp_tool.return_value = "MCP result"

    fake_run_context = create_fake_run_context(
        chat_session_id, message_id, fake_db_session, fake_redis_client, mcp_tool
    )

    # Act
    mcp_tool.run_v2(fake_run_context, query="test")

    # Assert - verify emitter captured packets
    emitter = fake_run_context.context.run_dependencies.emitter
    # Should have: CustomToolStart, CustomToolDelta
    assert len(emitter.packet_history) >= 2

    # Check CustomToolStart
    start_packet = emitter.packet_history[0]
    assert getattr(start_packet.obj, "type", None) == "custom_tool_start"
    assert start_packet.obj.tool_name == mcp_tool.name

    # Check CustomToolDelta
    delta_packet = emitter.packet_history[1]
    assert getattr(delta_packet.obj, "type", None) == "custom_tool_delta"
    assert delta_packet.obj.tool_name == mcp_tool.name
