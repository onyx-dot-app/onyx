import csv
import json
import uuid
from io import BytesIO, StringIO
from typing import Any, Dict, List

import requests
from pydantic import JsonValue, TypeAdapter
from requests import JSONDecodeError

from onyx.agents.tools import ToolInvocation
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.models import ToolResult
from onyx.tools.interface import FunctionToolDefinition, Tool, ToolContext
from onyx.tools.models import (
    CHAT_SESSION_ID_PLACEHOLDER,
    MESSAGE_ID_PLACEHOLDER,
    USER_EMAIL_PLACEHOLDER,
    USER_ID_PLACEHOLDER,
    CustomToolCallSummary,
    CustomToolErrorInfo,
    CustomToolUserFileSnapshot,
    DynamicSchemaInfo,
    ToolCallException,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    REQUEST_BODY,
    MethodSpec,
    openapi_to_method_specs,
    openapi_to_url,
)
from onyx.utils.headers import HeaderItemDict, header_list_to_header_dict
from onyx.utils.logger import setup_logger

logger = setup_logger()

CUSTOM_TOOL_RESPONSE_ID = "custom_tool_response"


class CustomTool(Tool):
    def __init__(
        self,
        id: int,
        method_spec: MethodSpec,
        base_url: str,
        custom_headers: list[HeaderItemDict] | None = None,
        user_oauth_token: str | None = None,
    ) -> None:

        self._base_url = base_url
        self._method_spec = method_spec
        self._tool_definition = TypeAdapter(FunctionToolDefinition).validate_python(
            self._method_spec.to_tool_definition()
        )
        self._user_oauth_token = user_oauth_token
        self._id = id

        self._name = self._method_spec.name
        self._description = self._method_spec.summary
        self.headers = (
            header_list_to_header_dict(custom_headers) if custom_headers else {}
        )

        # Check for both Authorization header and OAuth token
        has_auth_header = any(
            key.lower() == "authorization" for key in self.headers.keys()
        )
        if has_auth_header and self._user_oauth_token:
            logger.warning(
                "Tool '%s' has both an Authorization header and OAuth token set. This is likely a configuration error as the OAuth token will override the custom header.",
                self._name,
            )

        if self._user_oauth_token:
            self.headers["Authorization"] = f"Bearer {self._user_oauth_token}"

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
        # Show the original operationId in the UI, not the LLM-sanitized form
        # (e.g. "ServiceNow.GetIncident" vs "ServiceNow_GetIncident").
        return self._method_spec.raw_name

    def tool_definition(self) -> FunctionToolDefinition:
        return self._tool_definition

    def _save_and_get_file_references(
        self, file_content: bytes | str, content_type: str
    ) -> List[str]:
        file_store = get_default_file_store()

        file_id = str(uuid.uuid4())

        # Handle both binary and text content
        if isinstance(file_content, str):
            content = BytesIO(file_content.encode())
        else:
            content = BytesIO(file_content)

        file_store.save_file(
            file_id=file_id,
            content=content,
            display_name=file_id,
            file_origin=FileOrigin.CHAT_UPLOAD,
            file_type=content_type,
            file_metadata={
                "content_type": content_type,
            },
        )

        return [file_id]

    def _parse_csv(self, csv_text: str) -> List[Dict[str, Any]]:
        csv_file = StringIO(csv_text)
        reader = csv.DictReader(csv_file)
        return list(reader)

    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        path_params = {}
        for path_param_schema in self._method_spec.get_path_param_schemas():
            param_name = path_param_schema["name"]
            if param_name not in invocation.arguments:
                raise ToolCallException(
                    message=f"Missing required path parameter '{param_name}' in {self._name} tool call",
                    llm_facing_message=(
                        f"The {self._name} tool requires the '{param_name}' path parameter. "
                        f"Please provide it in the tool call arguments."
                    ),
                )
            path_params[param_name] = invocation.arguments[param_name]

        # Build query params
        query_params = {}
        for query_param_schema in self._method_spec.get_query_param_schemas():
            if query_param_schema["name"] in invocation.arguments:
                query_params[query_param_schema["name"]] = invocation.arguments[
                    query_param_schema["name"]
                ]

        request_body = invocation.arguments.get(REQUEST_BODY)
        url = self._method_spec.build_url(self._base_url, path_params, query_params)
        method = self._method_spec.method

        response = requests.request(
            method, url, json=request_body, headers=self.headers
        )
        content_type = response.headers.get("Content-Type", "")

        # Detect HTTP errors — only 401/403 are flagged as auth errors
        error_info: CustomToolErrorInfo | None = None
        if response.status_code in (401, 403):
            error_info = CustomToolErrorInfo(
                is_auth_error=True,
                status_code=response.status_code,
                message=f"{self._name} action failed because of authentication error",
            )
            logger.warning(
                "Auth error from custom tool '%s': HTTP %s",
                self._name,
                response.status_code,
            )

        tool_result: CustomToolUserFileSnapshot | JsonValue
        response_type: str

        if "text/csv" in content_type:
            file_ids = self._save_and_get_file_references(
                response.content, content_type
            )
            tool_result = CustomToolUserFileSnapshot(file_ids=file_ids)
            response_type = "csv"

        elif "image/" in content_type:
            file_ids = self._save_and_get_file_references(
                response.content, content_type
            )
            tool_result = CustomToolUserFileSnapshot(file_ids=file_ids)
            response_type = "image"

        else:
            try:
                tool_result = TypeAdapter(JsonValue).validate_python(response.json())
                response_type = "json"
            except JSONDecodeError:
                logger.exception(
                    "Failed to parse response as JSON for tool '%s'", self._name
                )
                tool_result = response.text
                response_type = "text"

        logger.info(
            "Returning tool response for %s with type %s", self._name, response_type
        )

        content = (
            TypeAdapter(CustomToolUserFileSnapshot | JsonValue)
            .dump_json(tool_result)
            .decode()
        )

        return ToolResult(
            details=CustomToolCallSummary(
                tool_name=self._name,
                response_type=response_type,
                tool_result=tool_result,
                error=error_info,
            ),
            content=content,
        )


def build_custom_tools_from_openapi_schema_and_headers(
    tool_id: int,
    openapi_schema: dict[str, Any],
    custom_headers: list[HeaderItemDict] | None = None,
    dynamic_schema_info: DynamicSchemaInfo | None = None,
    user_oauth_token: str | None = None,
) -> list[CustomTool]:
    """Build CustomTool instances from an OpenAPI schema.

    Placeholder substitution: when ``dynamic_schema_info`` is provided, the
    JSON-serialized schema is scanned for the following literal strings and
    each is replaced with the corresponding per-request value before the tool
    is built:

      - ``CHAT_SESSION_ID``  -> current chat session UUID
      - ``MESSAGE_ID``       -> current chat message id
      - ``USER_ID``          -> current user UUID (skipped for anonymous users)
      - ``USER_EMAIL``       -> current user email (skipped for anonymous users)

    Placeholders whose value is ``None`` (e.g. an anonymous user's identity)
    are left untouched in the schema rather than substituted with an empty
    string. Substitution only happens inside the OpenAPI schema; static
    ``custom_headers`` are not templated.
    """
    if dynamic_schema_info:
        schema_str = json.dumps(openapi_schema)
        placeholders = {
            CHAT_SESSION_ID_PLACEHOLDER: dynamic_schema_info.chat_session_id,
            MESSAGE_ID_PLACEHOLDER: dynamic_schema_info.message_id,
            USER_ID_PLACEHOLDER: dynamic_schema_info.user_id,
            USER_EMAIL_PLACEHOLDER: dynamic_schema_info.user_email,
        }

        for placeholder, value in placeholders.items():
            if value:
                schema_str = schema_str.replace(placeholder, str(value))

        openapi_schema = json.loads(schema_str)

    url = openapi_to_url(openapi_schema)
    method_specs = openapi_to_method_specs(openapi_schema)

    return [
        CustomTool(
            id=tool_id,
            method_spec=method_spec,
            base_url=url,
            custom_headers=custom_headers,
            user_oauth_token=user_oauth_token,
        )
        for method_spec in method_specs
    ]
