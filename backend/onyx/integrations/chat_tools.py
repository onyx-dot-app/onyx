"""The chat tools of the integrations that an agent can use.

Who can use an integration on an agent: a person who can use the agent and
can see a plugin of the agent that holds it. The user's on/off choice applies
only to the default agent, which uses each plugin the user runs. A caller
with no user sees the plugins of the Organization library and uses only an
integration with no sign-in or shared sign-in.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationAuthMode, IntegrationKind
from onyx.db.integration import list_integration_actions
from onyx.db.models import Integration, User
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import ActionSettings, EffectivePolicy
from onyx.integrations.policy import (
    agent_link_settings_by_integration,
    resolve_action_policies,
)
from onyx.integrations.registry import get_kind_handler
from onyx.tools.interface import Tool
from onyx.tools.models import IntegrationChatRequest, ToolApprovalScope
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _integration_tools(
    db_session: Session,
    integration: Integration,
    link_settings: Sequence[ActionSettings | None],
    plugin_ids: frozenset[UUID],
    user: User,
    request: IntegrationChatRequest,
) -> list[Tool]:
    """``link_settings``: every agent link that holds the integration.
    ``plugin_ids``: the plugins of those that the tool options allow."""
    kept_actions = _kept_actions(request, plugin_ids)
    acting_user = None if user.is_anonymous else user
    credentials = resolve_call_credentials(integration, acting_user, db_session)
    if isinstance(credentials, ConnectionProblem):
        logger.debug(
            "Skipping integration %s: %s", integration.id, credentials.code.value
        )
        return []
    actions = list_integration_actions(integration.id, db_session)
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
    )
    offered = [
        action
        for action in actions
        if policies[action.key] is not EffectivePolicy.BLOCKED
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
        additional_headers=request.additional_headers,
        mcp_headers=request.mcp_headers,
        approval_for=approval_for,
        plugin_ids=plugin_ids,
    )
    return get_kind_handler(integration.kind).build_chat_tools(
        integration, offered, ctx, db_session
    )


def _kept_actions(
    request: IntegrationChatRequest, plugin_ids: frozenset[UUID]
) -> frozenset[str] | None:
    if request.allowed_plugins is None:
        return None
    kept: frozenset[str] = frozenset()
    for plugin_id in plugin_ids:
        plugin_actions = request.allowed_plugins[plugin_id]
        if plugin_actions is None:
            return None
        kept |= plugin_actions
    return kept


def build_integration_chat_tools(
    db_session: Session, user: User, request: IntegrationChatRequest
) -> list[Tool]:
    """The tools of each enabled integration that the turn can use. An
    integration whose credential does not resolve gives no tool, and an API
    integration with no OpenAPI tool (a preset or custom app) gives none. A Blocked
    action gives no tool; an Ask action carries its approval scope."""
    held = agent_link_settings_by_integration(
        db_session,
        user.id,
        request.persona_id,
        {link.plugin_id: link.action_settings for link in request.plugin_links},
        published_only=user.is_anonymous,
    )
    # The tool options pick the integrations and actions. The settings of
    # every agent link still apply, so a request cannot drop a Blocked one.
    tools: list[Tool] = []
    for integration_id, links in held.items():
        integration = links.integration
        allowed = frozenset(
            plugin_id
            for plugin_id in links.plugin_ids
            if request.allowed_plugins is None or plugin_id in request.allowed_plugins
        )
        if (
            not allowed
            or not integration.enabled
            or (
                user.is_anonymous
                and integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
            )
            or (integration.kind is IntegrationKind.API and integration.tool_id is None)
        ):
            continue
        try:
            tools += _integration_tools(
                db_session, integration, links.settings, allowed, user, request
            )
        except Exception:
            # One broken integration does not stop the turn.
            logger.exception(
                "Could not build the chat tools of integration %s", integration_id
            )
    return tools
