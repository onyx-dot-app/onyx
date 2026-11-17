from collections import Counter
from collections.abc import Sequence

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationActionPolicyValue
from onyx.db.integration import (
    get_mcp_server_for_integration,
    list_integration_actions,
)
from onyx.db.models import Integration, IntegrationAction, MCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.kinds.base import IntegrationKindHandler
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import MatchedIntegrationAction, McpServerConfig
from onyx.sandbox_proxy.mcp_jsonrpc import classify_mcp_request
from onyx.sandbox_proxy.models import McpRpcKind
from onyx.sandbox_proxy.request_evaluator import MCP_UNCLASSIFIABLE_ACTION_TYPE
from onyx.sandbox_proxy.resolvers.mcp_matching import match_request, parse_target
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


def _blocked_unclassifiable(
    integration_id: int, description: str
) -> list[MatchedIntegrationAction]:
    return [
        MatchedIntegrationAction(
            integration_id=integration_id,
            action_key=MCP_UNCLASSIFIABLE_ACTION_TYPE,
            display_name="Unrecognized MCP request",
            description=description,
            default_policy=IntegrationActionPolicyValue.BLOCKED,
        )
    ]


class McpServerKindHandler(IntegrationKindHandler):
    """An MCP server. Its actions are the tools of the server, kept by the
    tool sync by name (``server/features/mcp/api.py``)."""

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
        server = self._server(integration, db_session)
        credentials = ctx.mcp_resolved_credentials
        if credentials is not None and not credentials.can_authenticate_with_headers(
            ctx.mcp_headers
        ):
            logger.debug("Skipping MCP server %s: credentials required", server.id)
            return []
        return [
            MCPTool(
                tool_id=action.id,
                mcp_server=server,
                tool_name=action.key,
                tool_description=action.description or "",
                tool_definition=action.input_schema or {},
                output_schema=action.output_schema,
                user_email=ctx.user_email or "",
                user_id=str(ctx.user_id) if ctx.user_id is not None else "",
                user_oauth_token=credentials.user_oauth_token if credentials else None,
                additional_headers=ctx.mcp_headers,
                resolved_credentials=credentials,
                approval=ctx.approval_for(action.key),
            )
            for action in actions
        ]

    def match_request(
        self,
        integration: Integration,
        request: ProxiedRequest,
        db_session: Session,
    ) -> list[MatchedIntegrationAction] | None:
        """Same rules as the sandbox proxy (``McpRequestEvaluator``): the host
        and the path prefix of the server URL attribute the request, and the
        JSON-RPC body gives the tools."""
        if request.url is None:
            return None
        server = self._server(integration, db_session)
        target = parse_target(server.id, server.server_url)
        if target is None:
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
        if match_request((target,), proxied) is None:
            return None

        try:
            classification = classify_mcp_request(proxied)
        except Exception:
            logger.exception("mcp_match_error integration=%s; denying", integration.id)
            return _blocked_unclassifiable(
                integration.id, "MCP gating failed; blocked."
            )
        if classification.kind is McpRpcKind.PLUMBING:
            return []
        if classification.kind is McpRpcKind.UNCLASSIFIABLE:
            path = (proxied.path or "").split("?", 1)[0]
            return _blocked_unclassifiable(
                integration.id,
                f"{request.method} {path} could not be parsed "
                "as an MCP tool call or protocol message; blocked.",
            )

        defaults = {
            action.key: action.default_policy
            or mcp_action_default_policy(action.read_only)
            for action in list_integration_actions(integration.id, db_session)
        }
        counts: Counter[str] = Counter(classification.tool_names)
        return [
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
