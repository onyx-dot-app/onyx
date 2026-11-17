"""The chat tools of the integrations that an agent can use.

Who can use an integration on an agent: a person who can use the agent and
can see a plugin of the agent that holds it. The user's on/off choice applies
only to the default agent, which uses each plugin the user runs. A caller
with no user sees the plugins of the Organization library and uses only an
integration with no sign-in or shared sign-in.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationAuthMode
from onyx.db.integration import list_integration_actions
from onyx.db.integration_policy import list_plugin_integrations
from onyx.db.models import Integration, User
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import ActionSettings, EffectivePolicy
from onyx.integrations.policy import agent_plugin_settings, resolve_action_policies
from onyx.integrations.registry import get_kind_handler
from onyx.integrations.sync import sync_api_actions_if_missing
from onyx.tools.interface import Tool
from onyx.tools.models import IntegrationChatRequest, ToolApprovalScope
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _integration_tools(
    db_session: Session,
    integration: Integration,
    settings: Sequence[ActionSettings | None],
    user: User,
    request: IntegrationChatRequest,
) -> list[Tool]:
    acting_user = None if user.is_anonymous else user
    credentials = resolve_call_credentials(integration, acting_user, db_session)
    if isinstance(credentials, ConnectionProblem):
        logger.debug(
            "Skipping integration %s: %s", integration.id, credentials.code.value
        )
        return []
    actions = list_integration_actions(integration.id, db_session)
    if not actions:
        # Read again also when another chat wrote the actions first.
        sync_api_actions_if_missing(integration.id)
        actions = list_integration_actions(integration.id, db_session)
    keys = [action.key for action in actions]
    policies = resolve_action_policies(
        db_session,
        integration=integration,
        action_keys=keys,
        user_id=acting_user.id if acting_user else None,
        link_settings=settings,
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
    )
    return get_kind_handler(integration.kind).build_chat_tools(
        integration, offered, ctx, db_session
    )


def build_integration_chat_tools(
    db_session: Session, user: User, request: IntegrationChatRequest
) -> list[Tool]:
    """The tools of each enabled integration that the turn can use. An
    integration whose credential does not resolve gives no tool. A Blocked
    action gives no tool; an Ask action carries its approval scope."""
    settings_by_plugin = agent_plugin_settings(
        db_session,
        user.id,
        request.persona_id,
        {link.plugin_id: link.action_settings for link in request.plugin_links},
        published_only=user.is_anonymous,
    )
    integrations: dict[int, Integration] = {}
    settings_by_integration: dict[int, list[ActionSettings | None]] = {}
    for plugin_id, integration in list_plugin_integrations(
        db_session, list(settings_by_plugin)
    ):
        if not integration.enabled:
            continue
        if (
            user.is_anonymous
            and integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
        ):
            continue
        integrations[integration.id] = integration
        settings_by_integration.setdefault(integration.id, []).append(
            settings_by_plugin[plugin_id]
        )

    tools: list[Tool] = []
    for integration_id, integration in integrations.items():
        try:
            tools += _integration_tools(
                db_session,
                integration,
                settings_by_integration[integration_id],
                user,
                request,
            )
        except Exception:
            # One broken integration does not stop the turn.
            logger.exception(
                "Could not build the chat tools of integration %s", integration_id
            )
    return tools
