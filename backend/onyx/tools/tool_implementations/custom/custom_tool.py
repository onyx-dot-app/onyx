import abc
import copy
import csv
import json
import uuid
from collections.abc import Callable
from io import BytesIO, StringIO
from typing import Any, Dict, List
from uuid import UUID

from pydantic import JsonValue, TypeAdapter

from onyx.agents.tools import ToolInvocation
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.models import CallCredentials
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.server.features.mcp.models import merge_mcp_headers
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CHAT_SESSION_ID_PLACEHOLDER,
    MESSAGE_ID_PLACEHOLDER,
    USER_EMAIL_PLACEHOLDER,
    USER_ID_PLACEHOLDER,
    CodeModeExposure,
    CustomToolCallSummary,
    CustomToolErrorInfo,
    CustomToolUserFileSnapshot,
    DynamicSchemaInfo,
    IntegrationActionRef,
    ToolApprovalScope,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    REQUEST_BODY,
    MethodSpec,
    openapi_operations,
    openapi_to_method_specs,
    openapi_to_url,
)
from onyx.tools.tool_implementations.http_request import (
    TOOL_REQUEST_FAILURE_MESSAGES,
    ToolRequestError,
    ToolRequestFailure,
    fresh_call_credentials,
    note_rejected_credential,
    send_tool_request,
    tool_request_ssrf_params,
)
from onyx.tools.tool_name import custom_tool_name
from onyx.utils.logger import setup_logger
from onyx.utils.url import validate_outbound_http_url

logger = setup_logger()

CUSTOM_TOOL_RESPONSE_ID = "custom_tool_response"


def validate_custom_tool_url(url: str, *, resolve_dns: bool = True) -> None:
    """Raises ``SSRFException`` or ``ValueError`` for a blocked destination."""
    params = tool_request_ssrf_params()
    validate_outbound_http_url(
        url,
        allow_private_network=params.allow_private_network,
        block_loopback_and_link_local=params.block_loopback_and_link_local,
        block_link_local_only=params.block_link_local_only,
        resolve_dns=resolve_dns,
    )


_OPERATION_POSITION_KEY = "x-onyx-operation-position"

_FAILURE_MESSAGES: dict[ToolRequestFailure, str] = {
    **TOOL_REQUEST_FAILURE_MESSAGES,
    ToolRequestFailure.REDIRECT: (
        "The {name} tool failed because the server sent a redirect. An admin "
        "must set the plugin's server URL to the final location."
    ),
}


class ApiTool(Tool):
    """A chat tool that sends one HTTP request to an API app. The caller
    renders the credential into ``headers``."""

    def __init__(
        self,
        *,
        integration_id: int,
        action_key: str,
        name: str,
        display_name: str,
        description: str,
        parameters: dict[str, JsonValue],
        base_url: str,
        headers: dict[str, str] | None,
        approval: ToolApprovalScope | None,
        credentials: CallCredentials | None = None,
        acting_user_id: UUID | None = None,
    ) -> None:
        self.approval = approval
        self.integration_action = IntegrationActionRef(
            integration_id=integration_id, action=action_key
        )
        self._name = name
        self._display_name = display_name
        self._description = description
        self._tool_definition = ToolDefinition(
            name=name, description=description, parameters=parameters
        )
        self._extra_headers = headers or {}
        self._credentials = credentials
        self._acting_user_id = acting_user_id
        self._base_url = base_url

    @property
    def headers(self) -> dict[str, str]:
        """The credential wins over a request header of the same name."""
        if self._credentials is None:
            return self._extra_headers
        return merge_mcp_headers(self._extra_headers, self._credentials.headers)

    @abc.abstractmethod
    def _request(self, arguments: dict[str, JsonValue]) -> tuple[str, str, JsonValue]:
        """The method, URL and JSON body of one call."""

    @property
    def id(self) -> int | None:
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

    def tool_definition(self) -> ToolDefinition:
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

    def _failed_response(
        self,
        status_code: int | None,
        message: str,
        is_unreachable: bool = False,
        is_auth_error: bool = False,
    ) -> ToolResult:
        return ToolResult(
            content=message,
            is_error=True,
            details=CustomToolCallSummary(
                tool_name=self._name,
                response_type="text",
                tool_result=None,
                error=CustomToolErrorInfo(
                    status_code=status_code,
                    message=message,
                    is_unreachable=is_unreachable,
                    is_auth_error=is_auth_error,
                ),
            ),
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        method, url, request_body = self._request(invocation.arguments)
        credentials = self._credentials
        if credentials is not None:
            fresh = fresh_call_credentials(credentials, self._acting_user_id)
            if isinstance(fresh, ConnectionProblem):
                return self._failed_response(
                    status_code=None,
                    message=f"{self._name} cannot authenticate: {fresh.reason}",
                    is_auth_error=True,
                )
            self._credentials = credentials = fresh
        try:
            response = send_tool_request(
                method,
                url,
                headers=self.headers,
                json_body=request_body,
            )
        except ToolRequestError as e:
            logger.warning(
                "%s request failed: %s", self._name, e.failure.value, exc_info=True
            )
            return self._failed_response(
                status_code=e.status_code,
                message=_FAILURE_MESSAGES[e.failure].format(name=self._name),
                is_unreachable=e.failure
                in (ToolRequestFailure.TIMEOUT, ToolRequestFailure.UNREACHABLE),
            )
        if credentials is not None:
            note_rejected_credential(response, credentials)
        content_type = response.content_type

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
            file_ids = self._save_and_get_file_references(response.body, content_type)
            tool_result = CustomToolUserFileSnapshot(file_ids=file_ids)
            response_type = "csv"

        elif "image/" in content_type:
            file_ids = self._save_and_get_file_references(response.body, content_type)
            tool_result = CustomToolUserFileSnapshot(file_ids=file_ids)
            response_type = "image"

        else:
            try:
                tool_result = json.loads(response.body)
                response_type = "json"
            except ValueError:
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
            is_error=not response.ok,
        )


class CustomTool(ApiTool):
    """One operation of an OpenAPI integration."""

    def __init__(
        self,
        integration_id: int,
        method_spec: MethodSpec,
        base_url: str,
        headers: dict[str, str] | None = None,
        approval: ToolApprovalScope | None = None,
        # The operationId before placeholder substitution.
        action_key: str | None = None,
        credentials: CallCredentials | None = None,
        acting_user_id: UUID | None = None,
    ) -> None:
        super().__init__(
            integration_id=integration_id,
            action_key=action_key or method_spec.raw_name,
            name=custom_tool_name(integration_id, method_spec.raw_name),
            # The original operationId, not the LLM-sanitized form (e.g.
            # "ServiceNow.GetIncident" vs "ServiceNow_GetIncident").
            display_name=method_spec.raw_name,
            description=method_spec.summary,
            parameters=method_spec.to_tool_definition().parameters,
            base_url=base_url,
            headers=headers,
            approval=approval,
            credentials=credentials,
            acting_user_id=acting_user_id,
        )
        self._method_spec = method_spec

    def _request(self, arguments: dict[str, JsonValue]) -> tuple[str, str, JsonValue]:
        path_params = {}
        for path_param_schema in self._method_spec.get_path_param_schemas():
            param_name = path_param_schema["name"]
            if param_name not in arguments:
                raise ToolCallException(
                    message=f"Missing required path parameter '{param_name}' in {self._name} tool call",
                    llm_facing_message=(
                        f"The {self._name} tool requires the '{param_name}' path parameter. "
                        f"Please provide it in the tool call arguments."
                    ),
                )
            path_params[param_name] = arguments[param_name]

        # Build query params
        query_params = {}
        for query_param_schema in self._method_spec.get_query_param_schemas():
            if query_param_schema["name"] in arguments:
                query_params[query_param_schema["name"]] = arguments[
                    query_param_schema["name"]
                ]

        url = self._method_spec.build_url(self._base_url, path_params, query_params)
        return self._method_spec.method, url, arguments.get(REQUEST_BODY)


def build_custom_tools_from_openapi_schema_and_headers(
    integration_id: int,
    openapi_schema: dict[str, Any],
    headers: dict[str, str] | None = None,
    dynamic_schema_info: DynamicSchemaInfo | None = None,
    approval_for: Callable[[str], ToolApprovalScope | None] | None = None,
    credentials: CallCredentials | None = None,
    acting_user_id: UUID | None = None,
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
    ``headers`` are not templated. ``approval_for`` gets the
    operationId from before the substitution.
    """
    action_keys: list[str] = []
    if dynamic_schema_info:
        # Mark each operation with its position, so that it keeps its own
        # action key when two paths render to the same path.
        marked_schema = copy.deepcopy(openapi_schema)
        for _, _, _, operation in openapi_operations(marked_schema):
            operation[_OPERATION_POSITION_KEY] = len(action_keys)
            action_keys.append(str(operation.get("operationId") or ""))
        schema_str = json.dumps(marked_schema)
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

    tools = []
    for method_spec in method_specs:
        position = method_spec.spec.pop(_OPERATION_POSITION_KEY, None)
        action_key = (
            action_keys[position] if position is not None else method_spec.raw_name
        )
        tools.append(
            CustomTool(
                integration_id=integration_id,
                method_spec=method_spec,
                base_url=url,
                headers=headers,
                approval=approval_for(action_key) if approval_for else None,
                action_key=action_key,
                credentials=credentials,
                acting_user_id=acting_user_id,
            )
        )
    return tools
