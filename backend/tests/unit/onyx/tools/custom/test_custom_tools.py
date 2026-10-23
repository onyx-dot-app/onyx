import unittest.mock
import uuid
from typing import Any
from unittest.mock import patch

import pytest
import requests

from onyx.agents.tools import ToolInvocation
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.server.features.tool.api import _validate_tool_definition
from onyx.server.security.models import SSRFProtectionLevel
from onyx.tools.interface import ToolContext
from onyx.tools.models import CustomToolCallSummary, DynamicSchemaInfo
from onyx.tools.tool_implementations.custom import custom_tool
from onyx.tools.tool_implementations.custom.custom_tool import (
    CUSTOM_TOOL_REQUEST_TIMEOUT,
    build_custom_tools_from_openapi_schema_and_headers,
    validate_custom_tool_url,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
    validate_openapi_schema,
)
from onyx.tools.tool_name import sanitize_tool_name
from onyx.utils.headers import HeaderItemDict
from onyx.utils.url import SSRFException

# Kwargs the tool passes on self-hosted below DISABLED.
_REQUEST_KWARGS: dict[str, Any] = {
    "timeout": CUSTOM_TOOL_REQUEST_TIMEOUT,
    "allow_private_network": True,
    "block_loopback_and_link_local": True,
    "block_link_local_only": False,
}


def _set_ssrf_level(
    monkeypatch: pytest.MonkeyPatch,
    level: SSRFProtectionLevel,
    multi_tenant: bool = False,
) -> None:
    settings = unittest.mock.MagicMock()
    settings.ssrf_protection_level = level
    monkeypatch.setattr(custom_tool, "get_security_settings", lambda: settings)
    monkeypatch.setattr(custom_tool, "MULTI_TENANT", multi_tenant)


@pytest.fixture(autouse=True)
def _self_hosted_default_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ssrf_level(monkeypatch, SSRFProtectionLevel.VALIDATE_ALL)


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

    @patch("onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request")
    def test_custom_tool_run_get(self, mock_request: unittest.mock.MagicMock) -> None:
        """
        Test the GET method of a custom tool.
        Verifies that the tool correctly constructs the URL and makes the GET request.
        """
        # Mock the response object
        mock_response = unittest.mock.MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123", "name": "Test Assistant"}
        mock_request.return_value = mock_response

        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        result = tools[0].run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={"assistant_id": "123"},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        assert isinstance(result, ToolResult)
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/123"
        mock_request.assert_called_once_with(
            expected_url, method="GET", json=None, headers={}, **_REQUEST_KWARGS
        )

        self.assertIsNotNone(result, "Expected a result from the tool run")
        self.assertIsNotNone(
            result.details,
            "Expected details to be set",
        )
        assert isinstance(result.details, CustomToolCallSummary)
        self.assertEqual(
            result.details.tool_name,
            "getAssistant",
            "Tool name in response does not match expected value",
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request")
    def test_custom_tool_run_post(self, mock_request: unittest.mock.MagicMock) -> None:
        """
        Test the POST method of a custom tool.
        Verifies that the tool correctly constructs the URL and makes the POST request with the given body.
        """
        # Mock the response object
        mock_response = unittest.mock.MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "456", "name": "Created Assistant"}
        mock_request.return_value = mock_response

        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        result = tools[1].run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={"assistant_id": "456"},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        assert isinstance(result, ToolResult)
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/456"
        mock_request.assert_called_once_with(
            expected_url, method="POST", json=None, headers={}, **_REQUEST_KWARGS
        )

        self.assertIsNotNone(result, "Expected a result from the tool run")
        self.assertIsNotNone(
            result.details,
            "Expected details to be set",
        )
        assert isinstance(result.details, CustomToolCallSummary)
        self.assertEqual(
            result.details.tool_name,
            "createAssistant",
            "Tool name in response does not match expected value",
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request")
    def test_custom_tool_with_headers(
        self, mock_request: unittest.mock.MagicMock
    ) -> None:
        """
        Test the custom tool with custom headers.
        Verifies that the tool correctly includes the custom headers in the request.
        """
        # Mock the response object
        mock_response = unittest.mock.MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123"}
        mock_request.return_value = mock_response

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

        tools[0].run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={"assistant_id": "123"},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/123"
        expected_headers = {
            "Authorization": "Bearer token123",
            "Custom-Header": "CustomValue",
        }
        mock_request.assert_called_once_with(
            expected_url,
            method="GET",
            json=None,
            headers=expected_headers,
            **_REQUEST_KWARGS,
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request")
    def test_custom_tool_with_empty_headers(
        self, mock_request: unittest.mock.MagicMock
    ) -> None:
        """
        Test the custom tool with an empty list of custom headers.
        Verifies that the tool correctly handles an empty list of headers.
        """
        # Mock the response object
        mock_response = unittest.mock.MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123"}
        mock_request.return_value = mock_response

        custom_headers: list[HeaderItemDict] = []
        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,  # dummy tool id
            openapi_schema=self.openapi_schema,
            custom_headers=custom_headers,
            dynamic_schema_info=self.dynamic_schema_info,
        )

        tools[0].run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={"assistant_id": "123"},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        expected_url = f"http://localhost:8080/{self.dynamic_schema_info.chat_session_id}/test/{self.dynamic_schema_info.message_id}/assistant/123"
        mock_request.assert_called_once_with(
            expected_url, method="GET", json=None, headers={}, **_REQUEST_KWARGS
        )

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

    @patch("onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request")
    def test_custom_tool_user_placeholders(
        self, mock_request: unittest.mock.MagicMock
    ) -> None:
        """USER_ID and USER_EMAIL placeholders are substituted across the
        OpenAPI schema (server URL, paths, headers) at tool-build time."""
        mock_response = unittest.mock.MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"ok": True}
        mock_request.return_value = mock_response

        user_id = uuid.uuid4()
        user_email = "alice@example.com"

        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "version": "1.0.0",
                "title": "User-aware API",
                "description": "Schema with USER_ID/USER_EMAIL placeholders",
            },
            "servers": [{"url": "http://localhost:8080/users/USER_ID"}],
            "paths": {
                "/by-email/{email}": {
                    "GET": {
                        "summary": "Lookup by email",
                        "operationId": "lookupByEmail",
                        "parameters": [
                            {
                                "name": "email",
                                "in": "path",
                                "required": True,
                                "schema": {
                                    "type": "string",
                                    "default": "USER_EMAIL",
                                },
                            }
                        ],
                    }
                }
            },
        }
        validate_openapi_schema(schema)

        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,
            openapi_schema=schema,
            custom_headers=[
                {"key": "X-Onyx-User-Id", "value": "USER_ID"},
                {
                    "key": "X-Onyx-User-Email",  # pragma: allowlist secret
                    "value": "USER_EMAIL",
                },
            ],
            dynamic_schema_info=DynamicSchemaInfo(
                chat_session_id=None,
                message_id=None,
                user_id=user_id,
                user_email=user_email,
            ),
        )

        tools[0].run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={"email": user_email},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )

        expected_url = (
            f"http://localhost:8080/users/{user_id}/by-email/alice%40example.com"
        )
        # Custom headers do NOT receive placeholder substitution today;
        # only the OpenAPI schema string is templated.
        expected_headers = {
            "X-Onyx-User-Id": "USER_ID",
            "X-Onyx-User-Email": "USER_EMAIL",
        }
        mock_request.assert_called_once_with(
            expected_url,
            method="GET",
            json=None,
            headers=expected_headers,
            **_REQUEST_KWARGS,
        )

    @patch("onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request")
    def test_custom_tool_user_placeholders_unset_are_left_alone(
        self, mock_request: unittest.mock.MagicMock
    ) -> None:
        """When user_id/user_email aren't provided (e.g. anonymous user),
        the literal placeholders remain in the schema rather than being
        replaced with empty strings."""
        mock_response = unittest.mock.MagicMock()
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"ok": True}
        mock_request.return_value = mock_response

        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "version": "1.0.0",
                "title": "User-aware API",
                "description": "Schema with USER_ID placeholder but no user",
            },
            "servers": [{"url": "http://localhost:8080/users/USER_ID"}],
            "paths": {
                "/ping": {
                    "GET": {
                        "summary": "Ping",
                        "operationId": "ping",
                    }
                }
            },
        }
        validate_openapi_schema(schema)

        tools = build_custom_tools_from_openapi_schema_and_headers(
            tool_id=-1,
            openapi_schema=schema,
            dynamic_schema_info=DynamicSchemaInfo(
                chat_session_id=None,
                message_id=None,
                user_id=None,
                user_email=None,
            ),
        )

        tools[0].run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )

        mock_request.assert_called_once_with(
            "http://localhost:8080/users/USER_ID/ping",
            method="GET",
            json=None,
            headers={},
            **_REQUEST_KWARGS,
        )

    def test_custom_tool_final_result(self) -> None:
        """
        Test extracting the final result from a custom tool response.
        Verifies that the tool result can be correctly extracted from the ToolResult.
        """
        mock_response = ToolResult(
            details=CustomToolCallSummary(
                response_type="json",
                tool_name="getAssistant",
                tool_result={"id": "789", "name": "Final Assistant"},
            ),
            content='{"id": "789", "name": "Final Assistant"}',
        )

        # Extract the final result from the details
        assert isinstance(mock_response.details, CustomToolCallSummary)
        final_result = mock_response.details.tool_result
        self.assertEqual(
            final_result,
            {"id": "789", "name": "Final Assistant"},
            "Final result does not match expected output",
        )


class TestSanitizeToolName(unittest.TestCase):
    """Tool names sent to Bedrock as toolUse.name must match [a-zA-Z0-9_-]+.
    User-supplied Tool.name and OpenAPI operationId can contain spaces or dots,
    so anything outside that set must be replaced with an underscore before the
    name reaches the LLM (in tool definitions or in message-history replay)."""

    def test_replaces_dots_and_spaces(self) -> None:
        self.assertEqual(
            sanitize_tool_name("ServiceNow.GetIncident"),
            "ServiceNow_GetIncident",
        )
        self.assertEqual(
            sanitize_tool_name("ServiceNow API"),
            "ServiceNow_API",
        )

    def test_preserves_valid_characters(self) -> None:
        self.assertEqual(
            sanitize_tool_name("get_assistant-v2"),
            "get_assistant-v2",
        )

    def test_operation_id_with_invalid_chars_is_sanitized(self) -> None:
        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {"title": "t", "description": "d", "version": "1.0.0"},
            "servers": [{"url": "http://x"}],
            "paths": {
                "/incidents": {
                    "get": {
                        "summary": "get incidents",
                        "operationId": "ServiceNow.list incidents",
                    }
                }
            },
        }
        specs = openapi_to_method_specs(schema)
        self.assertEqual(specs[0].name, "ServiceNow_list_incidents")
        # raw_name preserves the original operationId so the UI keeps showing
        # what the user wrote, even though the LLM sees the sanitized form.
        self.assertEqual(specs[0].raw_name, "ServiceNow.list incidents")
        self.assertEqual(
            specs[0].to_tool_definition().name,
            "ServiceNow_list_incidents",
        )

    def test_colliding_sanitized_names_raise(self) -> None:
        # Two distinct operationIds that sanitize to the same value would
        # silently overwrite each other in tools_by_name; surface a clear error.
        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {"title": "t", "description": "d", "version": "1.0.0"},
            "servers": [{"url": "http://x"}],
            "paths": {
                "/a": {
                    "get": {"summary": "a", "operationId": "foo.bar"},
                },
                "/b": {
                    "get": {"summary": "b", "operationId": "foo_bar"},
                },
            },
        }
        with pytest.raises(ValueError, match="sanitize to 'foo_bar'"):
            openapi_to_method_specs(schema)

    def test_duplicate_operation_id_raises(self) -> None:
        # The OpenAPI spec requires operationIds to be unique; a repeated
        # operationId would also collide in tools_by_name.
        schema: dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {"title": "t", "description": "d", "version": "1.0.0"},
            "servers": [{"url": "http://x"}],
            "paths": {
                "/a": {
                    "get": {"summary": "a", "operationId": "doThing"},
                },
                "/b": {
                    "get": {"summary": "b", "operationId": "doThing"},
                },
            },
        }
        with pytest.raises(ValueError, match="Duplicate operation ID 'doThing'"):
            openapi_to_method_specs(schema)


if __name__ == "__main__":
    pytest.main([__file__])


@pytest.mark.parametrize("status_code", [200, 401, 403, 500])
def test_custom_tool_http_outcome_sets_shared_error_flag(status_code: int) -> None:
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=1,
        openapi_schema={
            "openapi": "3.0.0",
            "info": {"title": "Status", "version": "1.0.0"},
            "servers": [{"url": "https://example.com"}],
            "paths": {
                "/status": {
                    "get": {
                        "operationId": "status",
                        "summary": "Get status",
                        "responses": {},
                    }
                }
            },
        },
    )
    response = requests.Response()
    response.status_code = status_code
    response.headers["Content-Type"] = "application/json"
    with (
        patch(
            "onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request",
            return_value=response,
        ),
        patch.object(response, "json", return_value={"message": "upstream response"}),
    ):
        result = tools[0].run(
            ToolInvocation(
                call_id="status",
                arguments={},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            ToolContext(),
        )
        assert isinstance(result, ToolResult)
    assert result.is_error is (status_code >= 400)
    assert "upstream response" in result.text


@pytest.mark.parametrize(
    ("content_type", "response_type"),
    [("text/csv", "csv"), ("image/png", "image")],
)
def test_custom_tool_file_response_is_serialized_for_llm(
    content_type: str, response_type: str
) -> None:
    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=1,
        openapi_schema={
            "openapi": "3.0.0",
            "info": {"title": "Files", "version": "1.0.0"},
            "servers": [{"url": "https://example.com"}],
            "paths": {
                "/file": {
                    "get": {
                        "operationId": "getFile",
                        "summary": "Get a file",
                        "responses": {},
                    }
                }
            },
        },
    )
    mock_response = unittest.mock.MagicMock()
    mock_response.is_redirect = False
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": content_type}
    mock_response.content = b"file-bytes"
    with (
        patch(
            "onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request",
            return_value=mock_response,
        ),
        patch.object(
            type(tools[0]),
            "_save_and_get_file_references",
            return_value=["file-1"],
        ),
    ):
        result = tools[0].run(
            ToolInvocation(
                call_id="file",
                arguments={},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            ToolContext(),
        )
        assert isinstance(result, ToolResult)

    assert isinstance(result.details, CustomToolCallSummary)
    assert result.details.response_type == response_type
    assert result.text == '{"file_ids":["file-1"]}'


def _schema(server_url: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Ping", "description": "Ping API", "version": "1.0.0"},
        "servers": [{"url": server_url}],
        "paths": {
            "/ping": {
                "post": {
                    "operationId": "ping",
                    "summary": "Ping",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    },
                }
            }
        },
    }


def _addr_info(ip: str) -> list[tuple[Any, ...]]:
    return [(None, None, None, "", (ip, 0))]


# In BLOCKED_HOSTNAMES, so the shared floor in utils/url.py blocks them even
# when custom-tool checks are off.
_METADATA_URLS = [
    "http://169.254.169.254/latest/meta-data",
    "http://[fd00:ec2::254]/",
    "http://metadata.google.internal/",
]
_PRIVATE_URLS = ["http://10.0.0.5", "http://192.168.1.10"]
_LOOPBACK_URL = "http://127.0.0.1:8080"
_BELOW_DISABLED_LEVELS = [
    SSRFProtectionLevel.VALIDATE_ALL,
    SSRFProtectionLevel.VALIDATE_LLM,
    SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK,
]


@pytest.mark.parametrize("multi_tenant", [False, True])
@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
@pytest.mark.parametrize("url", _METADATA_URLS)
def test_metadata_url_blocked_at_every_level(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    level: SSRFProtectionLevel,
    multi_tenant: bool,
) -> None:
    _set_ssrf_level(monkeypatch, level, multi_tenant)
    with pytest.raises(SSRFException):
        validate_custom_tool_url(url, resolve_dns=False)


@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
@pytest.mark.parametrize("url", _PRIVATE_URLS)
def test_private_url_allowed_on_self_hosted(
    monkeypatch: pytest.MonkeyPatch, url: str, level: SSRFProtectionLevel
) -> None:
    _set_ssrf_level(monkeypatch, level)
    validate_custom_tool_url(url, resolve_dns=False)


@pytest.mark.parametrize("level", _BELOW_DISABLED_LEVELS)
def test_loopback_blocked_on_self_hosted_below_disabled(
    monkeypatch: pytest.MonkeyPatch, level: SSRFProtectionLevel
) -> None:
    _set_ssrf_level(monkeypatch, level)
    with pytest.raises(SSRFException):
        validate_custom_tool_url(_LOOPBACK_URL, resolve_dns=False)


def test_loopback_allowed_on_self_hosted_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ssrf_level(monkeypatch, SSRFProtectionLevel.DISABLED)
    validate_custom_tool_url(_LOOPBACK_URL, resolve_dns=False)


_LINK_LOCAL_URLS = [
    "http://[fe80::1]/",
    "http://169.254.10.10/",
    "http://[::ffff:169.254.169.254]/latest/meta-data",
    "http://[::ffff:a9fe:a9fe]/",
]


@pytest.mark.parametrize("multi_tenant", [False, True])
@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
@pytest.mark.parametrize("url", _LINK_LOCAL_URLS)
def test_link_local_blocked_at_every_level(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    level: SSRFProtectionLevel,
    multi_tenant: bool,
) -> None:
    _set_ssrf_level(monkeypatch, level, multi_tenant)
    with pytest.raises(SSRFException):
        validate_custom_tool_url(url, resolve_dns=False)
    with patch("onyx.utils.url._pinned_request") as pinned:
        _assert_failed(_run_ping(url), status_code=None)
        pinned.assert_not_called()


@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
@pytest.mark.parametrize("url", [*_PRIVATE_URLS, _LOOPBACK_URL])
def test_private_and_loopback_blocked_on_cloud(
    monkeypatch: pytest.MonkeyPatch, url: str, level: SSRFProtectionLevel
) -> None:
    _set_ssrf_level(monkeypatch, level, multi_tenant=True)
    with pytest.raises(SSRFException):
        validate_custom_tool_url(url, resolve_dns=False)


def test_save_rejects_metadata_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ssrf_level(monkeypatch, SSRFProtectionLevel.VALIDATE_ALL)
    for blocked_url in ("http://169.254.169.254", _LOOPBACK_URL):
        with pytest.raises(OnyxError) as exc_info:
            _validate_tool_definition(_schema(blocked_url))
        assert exc_info.value.status_code == 400
    _validate_tool_definition(_schema("http://10.0.0.5"))


@pytest.mark.parametrize("servers", [[{"url": 123}], [{"url": "   "}], [{}], None])
def test_save_rejects_invalid_server_url(servers: list[dict[str, Any]] | None) -> None:
    schema = _schema("https://api.example.com")
    if servers is None:
        del schema["servers"]
    else:
        schema["servers"] = servers
    with pytest.raises(OnyxError) as exc_info:
        _validate_tool_definition(schema)
    assert exc_info.value.status_code == 400


def _run_ping(server_url: str) -> ToolResult:
    tool = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=1, openapi_schema=_schema(server_url)
    )[0]
    response = tool.run(
        ToolInvocation(
            call_id="ping",
            arguments={"requestBody": {"q": 1}},
            cancellation=CancellationSignal(),
            update=lambda _: None,
        ),
        ToolContext(),
    )
    assert isinstance(response, ToolResult)
    from onyx.chat.renderer import ToolRenderer
    from onyx.llm.models import ToolCall
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import CustomToolDelta

    packets = ToolRenderer(
        ToolCall(id="ping", name=tool.name, arguments={}),
        Placement(turn_index=0),
        tool_id=1,
    ).complete(response)
    deltas = [
        packet.obj for packet in packets if isinstance(packet.obj, CustomToolDelta)
    ]
    assert len(deltas) == 1
    assert isinstance(response.details, CustomToolCallSummary)
    error = deltas[0].error
    expected = response.details.error
    assert (error.model_dump() if error else None) == (
        expected.model_dump() if expected else None
    )
    return response


def _assert_failed(
    response: ToolResult, status_code: int | None, is_unreachable: bool = False
) -> None:
    assert isinstance(response.details, CustomToolCallSummary)
    assert response.is_error
    error = response.details.error
    assert error is not None
    assert not error.is_auth_error
    assert error.status_code == status_code
    assert error.is_unreachable == is_unreachable
    assert response.text == error.message


@pytest.mark.parametrize(
    ("level", "multi_tenant", "resolved_ip"),
    [
        (SSRFProtectionLevel.DISABLED, False, "169.254.169.254"),
        (SSRFProtectionLevel.VALIDATE_ALL, False, "127.0.0.1"),
        (SSRFProtectionLevel.DISABLED, True, "10.0.0.5"),
    ],
)
def test_call_blocks_host_resolving_to_blocked_ip(
    monkeypatch: pytest.MonkeyPatch,
    level: SSRFProtectionLevel,
    multi_tenant: bool,
    resolved_ip: str,
) -> None:
    _set_ssrf_level(monkeypatch, level, multi_tenant)
    with (
        patch(
            "onyx.utils.url.socket.getaddrinfo", return_value=_addr_info(resolved_ip)
        ),
        patch("onyx.utils.url._pinned_request") as pinned,
    ):
        _assert_failed(_run_ping("https://api.example.com"), status_code=None)
        pinned.assert_not_called()


def test_call_pins_private_ip_on_self_hosted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ssrf_level(monkeypatch, SSRFProtectionLevel.VALIDATE_ALL)
    response = unittest.mock.MagicMock()
    response.is_redirect = False
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {"ok": True}
    with (
        patch("onyx.utils.url.socket.getaddrinfo", return_value=_addr_info("10.0.0.5")),
        patch("onyx.utils.url._pinned_request", return_value=response) as pinned,
    ):
        _run_ping("http://internal.corp:8080")
    pinned.assert_called_once()
    args, kwargs = pinned.call_args
    assert args[:5] == (
        "post",
        "http://internal.corp:8080/ping",
        "10.0.0.5",
        "internal.corp",
        8080,
    )
    assert args[6] == CUSTOM_TOOL_REQUEST_TIMEOUT
    assert kwargs == {"json": {"q": 1}}


def test_call_refuses_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ssrf_level(monkeypatch, SSRFProtectionLevel.DISABLED)
    redirect = unittest.mock.MagicMock()
    redirect.is_redirect = True
    redirect.status_code = 302
    redirect.headers = {"Location": "http://169.254.169.254/latest/meta-data"}
    with (
        patch("onyx.utils.url.socket.getaddrinfo", return_value=_addr_info("8.8.8.8")),
        patch("onyx.utils.url._pinned_request", return_value=redirect) as pinned,
    ):
        _assert_failed(_run_ping("https://api.example.com"), status_code=302)
    pinned.assert_called_once()


def test_validate_all_allows_private_network_on_self_hosted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepted risk (ENG-4421): self-hosted custom tools reach RFC1918 hosts
    even at VALIDATE_ALL. Change this test only with a deliberate policy change."""
    _set_ssrf_level(monkeypatch, SSRFProtectionLevel.VALIDATE_ALL)
    _validate_tool_definition(_schema("http://10.0.0.1"))
    response = unittest.mock.MagicMock()
    response.is_redirect = False
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {"ok": True}
    with patch("onyx.utils.url._pinned_request", return_value=response) as pinned:
        result = _run_ping("http://10.0.0.1")
    pinned.assert_called_once()
    assert isinstance(result.details, CustomToolCallSummary)
    assert result.details.error is None


_RAW_URLLIB3_MESSAGE = (
    "HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded "
    "with url: /ping (Caused by ConnectTimeoutError("
    "<urllib3.connection.HTTPConnection object at 0x1>, "
    "'Connection to 10.255.255.1 timed out. (connect timeout=10)'))"
)


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (requests.exceptions.ConnectTimeout(_RAW_URLLIB3_MESSAGE), "(timed out)"),
        (requests.exceptions.ReadTimeout(_RAW_URLLIB3_MESSAGE), "(timed out)"),
        (
            requests.exceptions.ConnectionError(_RAW_URLLIB3_MESSAGE),
            "(connection failed)",
        ),
    ],
)
def test_call_network_error_returns_clean_message(
    error: requests.exceptions.RequestException, expected_reason: str
) -> None:
    with patch("onyx.utils.url._pinned_request", side_effect=error):
        response = _run_ping("http://10.255.255.1")
    _assert_failed(response, status_code=None, is_unreachable=True)
    assert response.text == (
        f"The ping tool could not reach its server {expected_reason}."
    )
    for internal_detail in ("urllib3", "HTTPConnectionPool", "Max retries", "10.255"):
        assert internal_detail not in response.text
