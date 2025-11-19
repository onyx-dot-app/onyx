import unittest
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.custom_tool import (
    CUSTOM_TOOL_RESPONSE_ID,
)
from onyx.tools.tool_implementations.custom.custom_tool import CustomToolCallSummary
from onyx.tools.tool_implementations.custom.custom_tool import (
    validate_openapi_schema,
)
from onyx.utils.headers import HeaderItemDict


class TestCustomTool(unittest.TestCase):
    """
    Test suite for CustomTool functionality.
    This class tests the creation, running, and result handling of custom tools
    based on OpenAPI schemas.
    """

    def setUp(self) -> None:
        """
        Set up the test environment before each test method.
        Initializes an OpenAPI schema and DynamicSchemaInfo for testing.
        """
        self.openapi_schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "version": "1.0.0",
                "title": "Assistants API",
                "description": "An API for managing assistants",
            },
            "servers": [
                {"url": "http://localhost:8080/CHAT_SESSION_ID/test/MESSAGE_ID"},
            ],
            "paths": {
                "/assistant/{assistant_id}": {
                    "GET": {
                        "summary": "Get a specific Assistant",
                        "operationId": "getAssistant",
                        "parameters": [
                            {
                                "name": "assistant_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                    },
                    "POST": {
                        "summary": "Create a new Assistant",
                        "operationId": "createAssistant",
                        "parameters": [
                            {
                                "name": "assistant_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            },
                        },
                    },
                }
            },
        }
        validate_openapi_schema(self.openapi_schema)
        self.dynamic_schema_info: DynamicSchemaInfo = DynamicSchemaInfo(
            chat_session_id=uuid.uuid4(), message_id=20
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
    def test_custom_tool_run_get(self, mock_request: unittest.mock.MagicMock) -> None:
        """
        Test the GET method of a custom tool.
        Verifies that the tool correctly constructs the URL and makes the GET request.
        """
        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        result = list(tools[0].run(assistant_id="123"))
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/123"
        mock_request.assert_called_once_with("GET", expected_url, json=None, headers={})

        self.assertEqual(
            len(result), 1, "Expected exactly one result from the tool run"
        )
        self.assertEqual(
            result[0].id,
            CUSTOM_TOOL_RESPONSE_ID,
            "Tool response ID does not match expected value",
        )
        self.assertEqual(
            result[0].response.tool_name,
            "getAssistant",
            "Tool name in response does not match expected value",
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
    def test_custom_tool_run_post(self, mock_request: unittest.mock.MagicMock) -> None:
        """
        Test the POST method of a custom tool.
        Verifies that the tool correctly constructs the URL and makes the POST request with the given body.
        """
        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        result = list(tools[1].run(assistant_id="456"))
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/456"
        mock_request.assert_called_once_with(
            "POST", expected_url, json=None, headers={}
        )

        self.assertEqual(
            len(result), 1, "Expected exactly one result from the tool run"
        )
        self.assertEqual(
            result[0].id,
            CUSTOM_TOOL_RESPONSE_ID,
            "Tool response ID does not match expected value",
        )
        self.assertEqual(
            result[0].response.tool_name,
            "createAssistant",
            "Tool name in response does not match expected value",
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
    def test_custom_tool_with_headers(
        self, mock_request: unittest.mock.MagicMock
    ) -> None:
        """
        Test the custom tool with custom headers.
        Verifies that the tool correctly includes the custom headers in the request.
        """
        custom_headers: list[HeaderItemDict] = [
            {"key": "Authorization", "value": "Bearer token123"},
            {"key": "Custom-Header", "value": "CustomValue"},
        ]
        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            custom_headers=custom_headers,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        list(tools[0].run(assistant_id="123"))
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/123"
        expected_headers = {
            "Authorization": "Bearer token123",
            "Custom-Header": "CustomValue",
        }
        mock_request.assert_called_once_with(
            "GET", expected_url, json=None, headers=expected_headers
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.requests.request")
    def test_custom_tool_with_empty_headers(
        self, mock_request: unittest.mock.MagicMock
    ) -> None:
        """
        Test the custom tool with an empty list of custom headers.
        Verifies that the tool correctly handles an empty list of headers.
        """
        custom_headers: list[HeaderItemDict] = []
        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            custom_headers=custom_headers,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        list(tools[0].run(assistant_id="123"))
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/123"
        mock_request.assert_called_once_with("GET", expected_url, json=None, headers={})

    def test_invalid_openapi_schema(self) -> None:
        """
        Test that an invalid OpenAPI schema raises a ValueError.
        """
        invalid_schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "version": "1.0.0",
                "title": "Invalid API",
            },
            # Missing required 'paths' key
        }

        with self.assertRaises(ValueError) as _:
            validate_openapi_schema(invalid_schema)

    def test_custom_tool_final_result(self) -> None:
        """
        Test the final_result method of a custom tool.
        Verifies that the method correctly extracts and returns the tool result.
        """
        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        mock_response = ToolResponse(
            id=CUSTOM_TOOL_RESPONSE_ID,
            response=CustomToolCallSummary(
                response_type="json",
                tool_name="getAssistant",
                tool_result={"id": "789", "name": "Final Assistant"},
            ),
        )

        final_result = tools[0].final_result(mock_response)
        self.assertEqual(
            final_result,
            {"id": "789", "name": "Final Assistant"},
            "Final result does not match expected output",
        )


if __name__ == "__main__":
    pytest.main([__file__])
