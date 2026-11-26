"""One chat tool for each action of a preset app.

The model sends a raw HTTP request. The tool sends it only when it is in the
URL scope of the app and is the one action of the tool, so the approval
decision that the runtime made for the tool name covers the request.
"""

import json
import re
from collections.abc import Sequence
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    recognize_actions,
    url_matches_patterns,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import graphql_endpoint_matches
from onyx.external_apps.providers.actions import GraphQLOp, MatchRule
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.models import CallCredentials
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.server.features.mcp.models import merge_mcp_headers
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CodeModeExposure,
    CustomToolCallSummary,
    CustomToolErrorInfo,
    IntegrationActionRef,
    ToolApprovalScope,
    ToolContext,
)
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.custom.graphql_tool import graphql_failed
from onyx.tools.tool_implementations.custom.openapi_parsing import TOOL_HTTP_METHODS
from onyx.tools.tool_implementations.http_request import (
    TOOL_REQUEST_FAILURE_MESSAGES,
    ToolRequestError,
    ToolRequestFailure,
    failed_tool_result,
    fresh_call_credentials,
    note_rejected_credential,
    send_tool_request,
)
from onyx.tools.tool_name import app_action_tool_name
from onyx.utils.logger import setup_logger

logger = setup_logger()

APP_ACTION_MAX_RESPONSE_BYTES = 1024 * 1024
# The request headers that the model can set. Each other header, and each
# header that the credential sets, comes from the server only.
_MODEL_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "if-match", "if-none-match"}
)
_VERSION_HEADER = re.compile(r"^[a-z0-9-]+-version$")

_FAILURE_MESSAGES: dict[ToolRequestFailure, str] = {
    **TOOL_REQUEST_FAILURE_MESSAGES,
    ToolRequestFailure.REDIRECT: (
        "The server sent a redirect, and redirects are not followed. "
        "Send the request to the final URL."
    ),
}


def _shown_url_scope(regex: str) -> str:
    """A built-in pattern is a regex; show it as a glob."""
    return re.sub(r"\\(.)", r"\1", regex.replace(".*", "*"))


def _shown_rule(rule: MatchRule) -> str:
    if isinstance(rule, GraphQLOp):
        return f"GraphQL {rule.operation_type} with the root field `{rule.field}`"
    return f"{rule.method.upper()} {rule.path}"


class AppActionSettings(BaseModel):
    """What the tools of one app share."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    integration_name: str
    app_type: ExternalAppType
    url_regexes: tuple[str, ...]
    credentials: CallCredentials
    acting_user_id: UUID | None
    # The action keys of the app that the turn offers.
    offered_keys: frozenset[str]


def _allowed_model_headers(raw: JsonValue | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        name: value
        for name, value in raw.items()
        if isinstance(value, str)
        and (name.lower() in _MODEL_HEADERS or _VERSION_HEADER.match(name.lower()))
    }


def _path_problem(path: str) -> str | None:
    """A path that a server or a client can read as a different path gives a
    request that is not the action it matched."""
    for segment in path.split("/"):
        # Decode until stable: a server that decodes twice reads "%252e" as ".".
        decoded = segment
        while (once := unquote(decoded)) != decoded:
            decoded = once
        if decoded in (".", "..") or "/" in decoded or "\\" in decoded:
            return "The URL path must not have '.', '..' or an encoded slash."
    return None


class AppActionTool(Tool):
    """One action of a preset app. The action ``unspecified`` is
    the request tool: each request in the URL scope that is no other action."""

    rank = ToolRank.INTEGRATION

    def __init__(
        self,
        settings: AppActionSettings,
        *,
        action_key: str,
        display_name: str,
        description: str,
        rules: Sequence[MatchRule],
        approval: ToolApprovalScope | None,
    ) -> None:
        self.approval = approval
        self.integration_action = IntegrationActionRef(
            integration_id=settings.integration_id, action=action_key
        )
        self._settings = settings
        self._credentials = settings.credentials
        self._action_key = action_key
        self._display_name = display_name
        self._name = app_action_tool_name(settings.integration_id, action_key)
        scope = ", ".join(_shown_url_scope(regex) for regex in settings.url_regexes)
        if action_key == WHOLE_DOMAIN_ACTION_TYPE:
            accepts = (
                "Accepts a request that no other tool of "
                f"{settings.integration_name} covers."
            )
        else:
            accepts = "Accepts only: " + "; ".join(_shown_rule(r) for r in rules) + "."
        self._description = (
            f"{settings.integration_name}: {description} {accepts} "
            f"The URL must match: {scope}. The credential is added for you: "
            "do not send an Authorization header."
        )

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
        return f"{self._settings.integration_name}: {self._display_name}"

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": list(TOOL_HTTP_METHODS)},
                    "url": {
                        "type": "string",
                        "description": "The full URL, with the query string.",
                    },
                    "body": {
                        "type": "object",
                        "description": (
                            "The JSON request body. For GraphQL: "
                            '{"query": "...", "variables": {...}}.'
                        ),
                    },
                    "headers": {
                        "type": "object",
                        "description": (
                            "Optional Accept, Content-Type or API version headers."
                        ),
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["method", "url"],
            },
        )

    def _failed(
        self, message: str, *, status_code: int | None = None, auth: bool = False
    ) -> ToolResult:
        return failed_tool_result(
            tool_name=self._name,
            integration_id=self._settings.integration_id,
            message=message,
            status_code=status_code,
            is_auth_error=auth,
        )

    def _wrong_action(self, matched: set[str]) -> str:
        """Which tools the request is for. An action with no tool is not
        available in this chat."""
        tools = [
            app_action_tool_name(self._settings.integration_id, key)
            if key in self._settings.offered_keys
            else "a tool that is not available"
            for key in sorted(matched)
        ]
        return f"This request is not for this tool. Send it with: {', '.join(tools)}."

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = invocation.arguments
        method = arguments.get("method")
        url = arguments.get("url")
        body = arguments.get("body")
        if not isinstance(method, str) or method.upper() not in TOOL_HTTP_METHODS:
            return self._failed(
                f"'method' must be one of {', '.join(TOOL_HTTP_METHODS)}."
            )
        if not isinstance(url, str):
            return self._failed("'url' must be a string.")
        method = method.upper()
        parts = urlsplit(url)
        if parts.username is not None or parts.password is not None or parts.fragment:
            return self._failed("The URL must not have user info or a fragment.")
        if not url_matches_patterns(url, self._settings.url_regexes):
            return self._failed(
                f"The URL is not a URL of {self._settings.integration_name}."
            )
        if problem := _path_problem(parts.path):
            return self._failed(problem)

        encoded_body = json.dumps(body).encode() if body is not None else None
        request = ProxiedRequest(
            method=method, path=parts.path, body=encoded_body, url=url
        )
        matched = {
            action.action_type
            for action in recognize_actions(self._settings.app_type, request)
        }
        if matched != {self._action_key}:
            return self._failed(self._wrong_action(matched))

        credentials = fresh_call_credentials(
            self._credentials, self._settings.acting_user_id
        )
        if isinstance(credentials, ConnectionProblem):
            return self._failed(
                f"{self._settings.integration_name} cannot authenticate: "
                f"{credentials.reason}",
                auth=True,
            )
        self._credentials = credentials

        try:
            response = send_tool_request(
                method,
                url,
                # The credential wins over a header of the same name.
                headers=merge_mcp_headers(
                    _allowed_model_headers(arguments.get("headers")),
                    credentials.headers,
                ),
                json_body=body,
                max_response_bytes=APP_ACTION_MAX_RESPONSE_BYTES,
            )
        except ToolRequestError as e:
            logger.warning("%s request failed: %s", self._name, e.failure.value)
            return self._failed(_FAILURE_MESSAGES[e.failure], status_code=e.status_code)

        note_rejected_credential(response, credentials)

        tool_result: JsonValue
        response_type = "text"
        if response.truncated:
            tool_result = (
                response.text
                + f"\n... [response cut at {APP_ACTION_MAX_RESPONSE_BYTES} bytes]"
            )
        else:
            try:
                tool_result = json.loads(response.body)
                response_type = "json"
            except ValueError:
                tool_result = response.text
        content = (
            tool_result if isinstance(tool_result, str) else json.dumps(tool_result)
        )
        if not response.ok:
            content = f"HTTP {response.status_code}\n{content}"
        return ToolResult(
            content=content,
            is_error=not response.ok
            or (
                any(
                    isinstance(rule, GraphQLOp)
                    and graphql_endpoint_matches(rule, request)
                    for endpoint in get_endpoint_catalog(self._settings.app_type)
                    for rule in endpoint.matches
                )
                and graphql_failed(tool_result)
            ),
            details=CustomToolCallSummary(
                tool_name=self._name,
                integration_id=self._settings.integration_id,
                response_type=response_type,
                tool_result=tool_result,
                error=(
                    CustomToolErrorInfo(
                        is_auth_error=True,
                        status_code=response.status_code,
                        message=f"{self._name} failed because of an authentication error",
                    )
                    # A 403 is a missing permission, and an app with no
                    # sign-in has nothing for the user to connect.
                    if response.status_code == 401
                    and credentials.auth_method is not None
                    else None
                ),
            ),
        )


class AppConnectTool(Tool):
    """The one tool of an app that the user can use on the agent and has no
    usable sign-in for. A call tells the model why the app does not work,
    and the chat shows the user a card that opens the sign-in."""

    rank = ToolRank.INTEGRATION

    def __init__(
        self,
        *,
        integration_id: int,
        integration_name: str,
        problem: ConnectionProblem,
        shared: bool,
    ) -> None:
        self._integration_id = integration_id
        self._integration_name = integration_name
        # Only an admin can fix a shared sign-in.
        self._user_can_connect = (
            not shared and problem.code is not ConnectionState.NOT_SET_UP
        )
        self._reason = problem.reason
        self._name = app_action_tool_name(integration_id, "connect")

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
        return (
            f"{self._integration_name} is available to the user but is not "
            "connected, so you have no other tool for it. Call this tool when "
            f"the user asks for something that needs {self._integration_name}: "
            "it asks the user to connect."
        )

    @property
    def display_name(self) -> str:
        return self._integration_name

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=self.description,
            parameters={"type": "object", "properties": {}},
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        message = (
            f"{self._integration_name} is not connected. The user now sees a "
            "card to connect it. Tell the user to connect and then to send the "
            "request again. Do not call this tool again in this response."
            if self._user_can_connect
            else f"{self._integration_name} cannot sign in: {self._reason} "
            "Tell the user that an admin must fix its sign-in."
        )
        return failed_tool_result(
            tool_name=self._name,
            integration_id=self._integration_id,
            message=message,
            is_auth_error=self._user_can_connect,
        )
