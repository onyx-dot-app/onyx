from collections import Counter
from collections.abc import Mapping, Sequence

from mcp.types import Tool as MCPLibTool
from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationKind,
    MCPTransport,
)
from onyx.db.integration import (
    get_mcp_server_for_integration,
    list_integration_actions,
)
from onyx.db.models import Integration, IntegrationAction, MCPServer, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.call_credentials import (
    mcp_oauth_provider,
    mcp_oauth_server,
    resolve_call_credentials,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import (
    ConnectionProblem,
    MissingHeaderValueError,
    render_headers,
)
from onyx.integrations.kinds.base import IntegrationKindHandler
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import (
    IntegrationActionSpec,
    MatchedIntegrationAction,
    McpServerConfig,
    RequestMatch,
)
from onyx.sandbox_proxy.mcp_jsonrpc import (
    MCP_UNCLASSIFIABLE_ACTION_TYPE,
    classify_mcp_request,
)
from onyx.sandbox_proxy.models import McpRpcKind
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    IntegrationMatchTarget,
    match_request,
)
from onyx.server.features.mcp.client import (
    discover_mcp_tools,
    has_auth_rejection_response,
)
from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def mcp_action_default_policy(read_only: bool | None) -> IntegrationActionPolicyValue:
    """A tool that the server marks read-only runs; each other tool asks."""
    return (
        IntegrationActionPolicyValue.ALLOW
        if read_only
        else IntegrationActionPolicyValue.ASK
    )


def mcp_tool_action_spec(tool: MCPLibTool) -> IntegrationActionSpec:
    annotations = tool.annotations
    read_only = annotations.readOnlyHint if annotations is not None else None
    return IntegrationActionSpec(
        key=tool.name,
        source=IntegrationActionSource.MCP,
        display_name=tool.title
        or (annotations.title if annotations is not None else None)
        or tool.name,
        description=tool.description,
        read_only=read_only,
        default_policy=mcp_action_default_policy(read_only),
        input_schema=tool.inputSchema,
        output_schema=tool.outputSchema,
    )


def fetch_mcp_actions(
    integration: Integration, acting_user: User | None, db_session: Session
) -> list[IntegrationActionSpec]:
    """Ask the MCP server for its tools with the credential of
    ``acting_user``: the organization connection of a shared server, or the
    connection of ``acting_user`` on an individual server. Raises a 400 when
    there is no usable credential or the server refuses it."""
    server = get_mcp_server_for_integration(integration.id, db_session)
    if server is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Integration {integration.id} has no MCP server settings.",
        )
    credentials = resolve_call_credentials(integration, acting_user, db_session)
    if isinstance(credentials, ConnectionProblem):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Connect {integration.name} first to load its actions.",
        )
    transport = server.transport or MCPTransport.STREAMABLE_HTTP
    oauth_server = mcp_oauth_server(integration, credentials, transport, db_session)
    try:
        tools = discover_mcp_tools(
            server.server_url,
            credentials.headers,
            transport=transport,
            auth=(
                mcp_oauth_provider(oauth_server, credentials)
                if oauth_server is not None
                else None
            ),
        )
    except Exception as error:
        if has_auth_rejection_response(error):
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                f"{integration.name} refused the credential. Reconnect it and try again.",
            ) from error
        raise
    return mcp_action_specs(tools)


def check_mcp_credential_fields(
    integration: Integration,
    fields: Mapping[str, str],
    user_email: str | None,
    db_session: Session,
) -> None:
    """Ask the MCP server of an API key integration for its tools with the
    headers that ``fields`` give. Raises CREDENTIAL_INVALID when the server
    refuses them. Other failures only log, so a save does not wait for a
    server that is down."""
    if (
        integration.kind is not IntegrationKind.MCP
        or integration.auth_method is not IntegrationAuthMethod.API_KEY
    ):
        return
    server = get_mcp_server_for_integration(integration.id, db_session)
    if server is None:
        return
    try:
        headers = render_headers(
            integration.header_template,
            ConnectionSecret(fields=dict(fields)),
            extra_values={"user_email": user_email} if user_email else None,
        )
    except MissingHeaderValueError:
        # The save refuses the missing fields with its own message.
        return
    try:
        discover_mcp_tools(
            server.server_url,
            headers,
            transport=server.transport or MCPTransport.STREAMABLE_HTTP,
        )
    except Exception as error:
        if has_auth_rejection_response(error):
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                f"{integration.name} refused the key. Check it and try again.",
            ) from error
        logger.warning(
            "Could not check the key of integration %s: %s", integration.id, error
        )


def mcp_action_specs(tools: Sequence[MCPLibTool]) -> list[IntegrationActionSpec]:
    """One spec for each tool name; the first tool of a name wins."""
    specs: dict[str, IntegrationActionSpec] = {}
    for tool in tools:
        if tool.name and tool.name not in specs:
            try:
                specs[tool.name] = mcp_tool_action_spec(tool)
            except ValueError as e:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    return list(specs.values())


def _blocked_unclassifiable(
    integration_id: int, description: str, path_prefix_length: int
) -> RequestMatch:
    return RequestMatch(
        actions=[
            MatchedIntegrationAction(
                integration_id=integration_id,
                action_key=MCP_UNCLASSIFIABLE_ACTION_TYPE,
                display_name="Unrecognized MCP request",
                description=description,
                default_policy=IntegrationActionPolicyValue.BLOCKED,
            )
        ],
        path_prefix_length=path_prefix_length,
    )


class McpServerKindHandler(IntegrationKindHandler):
    """An MCP server. Its actions are the tools of the server, stored as
    ``integration_action`` rows by ``fetch_mcp_actions``."""

    def _server(self, integration: Integration, db_session: Session) -> MCPServer:
        server = get_mcp_server_for_integration(integration.id, db_session)
        if server is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"Integration {integration.id} has no MCP server settings.",
            )
        return server

    def load_config(
        self, integration: Integration, db_session: Session
    ) -> McpServerConfig:
        server = self._server(integration, db_session)
        return self.config_from_server(server)

    @staticmethod
    def config_from_server(server: MCPServer) -> McpServerConfig:
        return McpServerConfig(
            mcp_server_id=server.id,
            server_url=server.server_url,
            transport=server.transport,
        )

    def build_chat_tools(
        self,
        integration: Integration,
        actions: Sequence[IntegrationAction],
        ctx: ChatToolContext,
        db_session: Session,
    ) -> list[Tool]:
        if not actions:
            return []
        server = (
            ctx.config
            if isinstance(ctx.config, McpServerConfig)
            else self.load_config(integration, db_session)
        )
        oauth_server = mcp_oauth_server(
            integration, ctx.credentials, server.transport, db_session
        )
        return [
            MCPTool(
                integration_id=integration.id,
                integration_name=integration.name,
                integration_description=integration.description,
                server_url=server.server_url,
                transport=server.transport,
                tool_name=action.key,
                tool_description=action.description or "",
                tool_definition=action.input_schema or {},
                output_schema=action.output_schema,
                acting_user_id=ctx.user_id,
                credentials=ctx.credentials,
                oauth_server=oauth_server,
                additional_headers=ctx.mcp_headers,
                approval=ctx.approval_for(action.key),
            )
            for action in actions
        ]

    def match_request(
        self,
        integration: Integration,
        target: IntegrationMatchTarget,
        request: ProxiedRequest,
        db_session: Session,
    ) -> RequestMatch | None:
        """The host and the path prefix of the server URL attribute the
        request, and the JSON-RPC body gives the tools. The caller picks the
        longest prefix when servers share a host."""
        if request.url is None or target.endpoint is None:
            return None
        proxied = http.Request.make(
            request.method,
            request.url,
            content=request.body or b"",
            headers=[
                (name.encode(), value.encode())
                for name, value in request.headers.items()
            ],
        )
        if match_request((target.endpoint,), proxied) is None:
            return None
        prefix_length = len(target.endpoint.path_prefix)

        try:
            classification = classify_mcp_request(proxied)
        except Exception:
            logger.exception("mcp_match_error integration=%s; denying", integration.id)
            return _blocked_unclassifiable(
                integration.id, "MCP gating failed; blocked.", prefix_length
            )
        if classification.kind is McpRpcKind.PLUMBING:
            return RequestMatch(actions=[], path_prefix_length=prefix_length)
        if classification.kind is McpRpcKind.UNCLASSIFIABLE:
            path = (proxied.path or "").split("?", 1)[0]
            return _blocked_unclassifiable(
                integration.id,
                f"{request.method} {path} could not be parsed "
                "as an MCP tool call or protocol message; blocked.",
                prefix_length,
            )

        defaults = {
            action.key: action.default_policy
            or mcp_action_default_policy(action.read_only)
            for action in list_integration_actions(integration.id, db_session)
        }
        counts: Counter[str] = Counter(classification.tool_names)
        actions = [
            MatchedIntegrationAction(
                integration_id=integration.id,
                action_key=tool_name,
                display_name=tool_name,
                description=(
                    f"Call the “{tool_name}” tool on {integration.name}."
                    + (f" This request invokes it {count} times." if count > 1 else "")
                ),
                default_policy=defaults.get(
                    tool_name, IntegrationActionPolicyValue.ASK
                ),
            )
            for tool_name, count in counts.items()
        ]
        return RequestMatch(actions=actions, path_prefix_length=prefix_length)
