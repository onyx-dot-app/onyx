"""The chat tools of the integrations that an agent can use.

Who can use an integration on an agent: a person who can use the agent and
has access to the integration. The user's on/off choice applies only to the
default agent, which uses each integration that the user turned on. A caller
with no user gets the integrations that each user has, and uses only an
integration with no sign-in or shared sign-in.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationAuthMode, PluginInstallationPolicy
from onyx.db.integration import (
    list_api_apps_by_integration,
    list_external_apps_by_integration,
    list_mcp_servers_by_integration,
)
from onyx.db.integration_connection import list_connections
from onyx.db.integration_policy import list_policy_rows, list_session_granted_actions
from onyx.db.models import Integration, IntegrationAction, IntegrationConnection, User
from onyx.integrations.actions import integration_actions_by_id
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.kinds.mcp_server import McpServerKindHandler
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import (
    ActionSettings,
    ApiConfig,
    ApiShape,
    EffectivePolicy,
    IntegrationConfig,
    PolicyRows,
)
from onyx.integrations.policy import (
    AgentIntegration,
    chat_integrations,
    resolve_action_policies,
)
from onyx.integrations.registry import get_kind_handler
from onyx.tools.interface import Tool
from onyx.tools.models import IntegrationChatRequest, ToolApprovalScope
from onyx.tools.tool_implementations.app_action.app_action_tool import AppConnectTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _integration_tools(
    db_session: Session,
    integration: Integration,
    link_settings: ActionSettings,
    kept_actions: frozenset[str] | None,
    user: User,
    request: IntegrationChatRequest,
    *,
    actions: Sequence[IntegrationAction],
    connections: Mapping[tuple[int, UUID | None], IntegrationConnection] | None = None,
    policy_rows: PolicyRows | None = None,
    granted_actions: set[str] | None = None,
    config: IntegrationConfig | None = None,
) -> list[Tool]:
    """``link_settings``: the settings of the agent for the integration.
    ``kept_actions``: the action keys that the tool options keep; None keeps
    each."""
    acting_user = None if user.is_anonymous else user
    actions = [
        action
        for action in actions
        if kept_actions is None or action.key in kept_actions
    ]
    policies = resolve_action_policies(
        db_session,
        integration=integration,
        actions=actions,
        action_keys=[action.key for action in actions],
        user_id=acting_user.id if acting_user else None,
        link_settings=link_settings,
        approval_mode=request.approval_mode,
        chat_session_id=request.chat_session_id,
        policy_rows=policy_rows,
        granted_actions=granted_actions,
    )
    offered = [
        action
        for action in actions
        if policies[action.key] is not EffectivePolicy.BLOCKED
    ]
    credentials = resolve_call_credentials(
        integration, acting_user, db_session, connections=connections
    )
    if isinstance(credentials, ConnectionProblem):
        logger.debug(
            "Integration %s has no credential: %s",
            integration.id,
            credentials.code.value,
        )
        if (
            acting_user is None
            or not isinstance(config, ApiConfig)
            or config.shape is ApiShape.CUSTOM
            or not offered
        ):
            return []
        # A preset, OpenAPI or GraphQL app: one tool that asks the user to connect.
        return [
            AppConnectTool(
                integration_id=integration.id,
                integration_name=integration.name,
                problem=credentials,
            )
        ]

    def approval_for(action_key: str) -> ToolApprovalScope | None:
        # Ask is left only in an interactive run.
        if policies.get(action_key) is EffectivePolicy.ASK:
            return ToolApprovalScope(
                integration_id=integration.id, action_id=action_key
            )
        return None

    ctx = ChatToolContext(
        user_id=acting_user.id if acting_user else None,
        user_email=acting_user.email if acting_user else None,
        chat_session_id=request.chat_session_id,
        message_id=request.message_id,
        credentials=credentials,
        config=config,
        additional_headers=request.additional_headers,
        mcp_headers=request.mcp_headers,
        approval_for=approval_for,
    )
    return get_kind_handler(integration.kind).build_chat_tools(
        integration, offered, ctx, db_session
    )


def _keep_required_integrations(
    user: User,
    request: IntegrationChatRequest,
    held: Mapping[int, AgentIntegration],
) -> IntegrationChatRequest:
    """Add each integration that the admin made Required for the user to the
    tool options, with all its actions. A member cannot turn a Required
    integration off, so tool options that leave it out cannot drop it."""
    if request.allowed_integrations is None or user.is_anonymous:
        return request
    required = {
        integration_id
        for integration_id, agent_integration in held.items()
        if agent_integration.installation_policy == PluginInstallationPolicy.REQUIRED
        and integration_id not in request.allowed_integrations
    }
    if not required:
        return request
    return request.model_copy(
        update={
            "allowed_integrations": {
                **request.allowed_integrations,
                **dict.fromkeys(required),
            }
        }
    )


def build_integration_chat_tools(
    db_session: Session, user: User, request: IntegrationChatRequest
) -> list[Tool]:
    """The tools of each enabled integration that the turn can use. An
    integration whose credential does not resolve gives no tool, except that
    a preset, OpenAPI or GraphQL app gives one tool that asks the user to
    connect. An API integration with neither an ``api_app`` nor a preset
    gives none. A Blocked action gives no tool; an Ask action carries its
    approval scope."""
    held = chat_integrations(
        db_session,
        user.id,
        request.persona_id,
        {
            link.integration_id: link.action_settings
            for link in request.integration_links
        },
        request.chat_session_id,
        for_everyone_only=user.is_anonymous,
    )
    request = _keep_required_integrations(user, request, held)
    # The tool options pick the integrations and actions. The settings of
    # the agent link still apply, so a request cannot drop a Blocked one.
    allowed = request.allowed_integrations
    selected = {
        integration_id: agent_integration
        for integration_id, agent_integration in held.items()
        if (allowed is None or integration_id in allowed)
        and agent_integration.integration.enabled
        and not (
            user.is_anonymous
            and agent_integration.integration.auth_mode
            is IntegrationAuthMode.INDIVIDUAL
        )
    }
    user_id = None if user.is_anonymous else user.id
    actions = integration_actions_by_id(list(selected), db_session)
    connections = list_connections(db_session, list(selected), user_id)
    policies = list_policy_rows(db_session, list(selected), user_id)
    grants = list_session_granted_actions(
        db_session, request.chat_session_id, list(selected)
    )
    api_apps = list_api_apps_by_integration(list(selected), db_session)
    apps = list_external_apps_by_integration(list(selected), db_session)
    servers = list_mcp_servers_by_integration(list(selected), db_session)
    tools: list[Tool] = []
    for integration_id, agent_integration in selected.items():
        integration = agent_integration.integration
        try:
            config: IntegrationConfig | None = None
            if integration_id in api_apps:
                config = ApiKindHandler.config_from_api_app(api_apps[integration_id])
            elif integration_id in apps:
                config = ApiKindHandler.config_from_external_app(apps[integration_id])
            elif integration_id in servers:
                config = McpServerKindHandler.config_from_server(
                    servers[integration_id]
                )
            tools += _integration_tools(
                db_session,
                integration,
                agent_integration.settings,
                None if allowed is None else allowed[integration_id],
                user,
                request,
                actions=actions[integration_id],
                connections=connections,
                policy_rows=(
                    PolicyRows(admin=policies[integration_id].admin, user={})
                    if agent_integration.task_link
                    else policies[integration_id]
                ),
                granted_actions=grants[integration_id],
                config=config,
            )
        except Exception:
            # One broken integration does not stop the turn.
            logger.exception(
                "Could not build the chat tools of integration %s", integration_id
            )
    return tools
