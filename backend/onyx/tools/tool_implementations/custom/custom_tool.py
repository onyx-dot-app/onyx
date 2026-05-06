import csv
import json
import queue
import uuid
from io import BytesIO
from io import StringIO
from typing import Any
from typing import Dict
from typing import List

import requests
from requests import JSONDecodeError

from onyx.chat.emitter import Emitter
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolArgs
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolErrorInfo
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import CHAT_SESSION_ID_PLACEHOLDER
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.models import CustomToolUserFileSnapshot
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.models import MESSAGE_ID_PLACEHOLDER
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.models import USER_EMAIL_PLACEHOLDER
from onyx.tools.models import USER_ID_PLACEHOLDER
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import openapi_to_url
from onyx.tools.tool_implementations.custom.openapi_parsing import REQUEST_BODY
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    validate_openapi_schema,
)
from onyx.utils.headers import header_list_to_header_dict
from onyx.utils.headers import HeaderItemDict
from onyx.utils.logger import setup_logger

logger = setup_logger()

CUSTOM_TOOL_RESPONSE_ID = "custom_tool_response"


# override_kwargs is not supported for custom tools
class CustomTool(Tool[None]):
    def __init__(
        self,
        id: int,
        method_spec: MethodSpec,
        base_url: str,
        emitter: Emitter,
        custom_headers: list[HeaderItemDict] | None = None,
        user_oauth_token: str | None = None,
    ) -> None:
        super().__init__(emitter=emitter)

        self._base_url = base_url
        self._method_spec = method_spec
        self._tool_definition = self._method_spec.to_tool_definition()
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
        return self._name

    def tool_definition(self) -> dict:
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
        return [row for row in reader]

    """Actual execution of the tool"""

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=self._name, tool_id=self._id),
            )
        )

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        # Build path params
        path_params = {}
        for path_param_schema in self._method_spec.get_path_param_schemas():
            param_name = path_param_schema["name"]
            if param_name not in llm_kwargs:
                raise ToolCallException(
                    message=f"Missing required path parameter '{param_name}' in {self._name} tool call",
                    llm_facing_message=(
                        f"The {self._name} tool requires the '{param_name}' path parameter. "
                        f"Please provide it in the tool call arguments."
                    ),
                )
            path_params[param_name] = llm_kwargs[param_name]

        # Build query params
        query_params = {}
        for query_param_schema in self._method_spec.get_query_param_schemas():
            if query_param_schema["name"] in llm_kwargs:
                query_params[query_param_schema["name"]] = llm_kwargs[
                    query_param_schema["name"]
                ]

        # Emit args packet (path + query params only, no request body)
        tool_args = {**path_params, **query_params}
        if tool_args:
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=CustomToolArgs(
                        tool_name=self._name,
                        tool_args=tool_args,
                    ),
                )
            )

        request_body = llm_kwargs.get(REQUEST_BODY)
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

        tool_result: Any
        response_type: str
        file_ids: List[str] | None = None
        data: dict | list | str | int | float | bool | None = None

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
                tool_result = response.json()
                response_type = "json"
                data = tool_result
            except JSONDecodeError:
                logger.exception(
                    "Failed to parse response as JSON for tool '%s'", self._name
                )
                tool_result = response.text
                response_type = "text"
                data = tool_result

        logger.info(
            "Returning tool response for %s with type %s", self._name, response_type
        )

        # Emit CustomToolDelta packet
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolDelta(
                    tool_name=self._name,
                    tool_id=self._id,
                    response_type=response_type,
                    data=data,
                    file_ids=file_ids,
                    error=error_info,
                ),
            )
        )

        llm_facing_response = json.dumps(tool_result)

        return ToolResponse(
            rich_response=CustomToolCallSummary(
                tool_name=self._name,
                response_type=response_type,
                tool_result=tool_result,
                error=error_info,
            ),
            llm_facing_response=llm_facing_response,
        )


def build_custom_tools_from_openapi_schema_and_headers(
    tool_id: int,
    openapi_schema: dict[str, Any],
    emitter: Emitter | None = None,
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

    # Use a discard emitter if none provided (packets go nowhere)
    if emitter is None:
        emitter = Emitter(merged_queue=queue.Queue())

    return [
        CustomTool(
            id=tool_id,
            method_spec=method_spec,
            base_url=url,
            emitter=emitter,
            custom_headers=custom_headers,
            user_oauth_token=user_oauth_token,
        )
        for method_spec in method_specs
    ]


if __name__ == "__main__":
    import openai
    from openai.types.chat.chat_completion_message_function_tool_call import (
        ChatCompletionMessageFunctionToolCall,
    )

    openapi_schema = {
        "openapi": "3.0.0",
        "info": {
            "version": "1.0.0",
            "title": "Assistants API",
            "description": "An API for managing assistants",
        },
        "servers": [
            {"url": "http://localhost:8080"},
        ],
        "paths": {
            "/assistant/{assistant_id}": {
                "get": {
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
                "post": {
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
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                },
            }
        },
    }
    validate_openapi_schema(openapi_schema)

    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=0,  # dummy tool id
        openapi_schema=openapi_schema,
        emitter=Emitter(merged_queue=queue.Queue()),
        dynamic_schema_info=None,
    )

    openai_client = openai.OpenAI()
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Can you fetch assistant with ID 10"},
        ],
        tools=[  # ty: ignore[invalid-argument-type]
            tool.tool_definition() for tool in tools
        ],
    )
    choice = response.choices[0]
    if choice.message.tool_calls:
        print(choice.message.tool_calls)
        tool_call = choice.message.tool_calls[0]
        if isinstance(tool_call, ChatCompletionMessageFunctionToolCall):
            # Note: This example code would need a proper run_context with emitter
            # For testing purposes, this would need to be updated
            print("Tool execution requires run_context with emitter")
