"""Pytest fixtures for chat turn tests."""

from collections.abc import Generator
from typing import Any

import pytest

from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.custom.custom_tool import CUSTOM_TOOL_RESPONSE_ID
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.custom.custom_tool import CustomToolCallSummary
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec
from tests.unit.onyx.chat.turn.utils import chat_turn_context
from tests.unit.onyx.chat.turn.utils import chat_turn_dependencies
from tests.unit.onyx.chat.turn.utils import fake_db_session
from tests.unit.onyx.chat.turn.utils import fake_llm
from tests.unit.onyx.chat.turn.utils import fake_model
from tests.unit.onyx.chat.turn.utils import fake_redis_client
from tests.unit.onyx.chat.turn.utils import fake_tools


class FakeDummyTool(CustomTool):
    """A fake custom tool for testing context handlers."""

    def __init__(self) -> None:
        # Create a minimal MethodSpec for the tool following OpenAPI spec format
        method_spec = MethodSpec(
            name="dummy_tool",
            summary="A dummy tool for testing",
            method="get",
            path="/dummy",
            spec={
                "summary": "A dummy tool for testing",
                "description": "A dummy tool for testing context handlers",
                "operationId": "dummy_tool",
                "parameters": [],
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                        "message": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            },
        )
        # Initialize with minimal required args
        super().__init__(
            id=1,
            method_spec=method_spec,
            base_url="http://dummy.test",
            custom_headers=None,
            user_oauth_token=None,
        )

    def run(
        self, override_kwargs: dict[str, Any] | None = None, **kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        """Override run to return a fixed response without making HTTP calls."""
        # Return the response in the format CustomTool expects
        yield ToolResponse(
            id=CUSTOM_TOOL_RESPONSE_ID,
            response=CustomToolCallSummary(
                tool_name="dummy_tool",
                response_type="json",
                tool_result={
                    "status": "success",
                    "message": "Tool executed successfully",
                },
            ),
        )


@pytest.fixture
def fake_dummy_tool() -> FakeDummyTool:
    """Fixture providing a fake custom tool for testing."""
    return FakeDummyTool()


__all__ = [
    "chat_turn_context",
    "chat_turn_dependencies",
    "fake_db_session",
    "fake_dummy_tool",
    "fake_llm",
    "fake_model",
    "fake_redis_client",
    "fake_tools",
]
