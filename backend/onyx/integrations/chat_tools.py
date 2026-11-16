"""The chat tools of the integrations that an agent can use.

Who can use an integration on an agent: a person who can use the agent and
can see a plugin of the agent that holds it. The user's on/off choice applies
only to the default agent, which uses each plugin the user runs. A caller
with no user sees the plugins of the Organization library and uses only an
integration with no sign-in or shared sign-in.
"""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.enums import IntegrationAuthMode
from onyx.db.integration import list_integration_actions
from onyx.db.integration_policy import list_plugin_integrations
from onyx.db.models import Integration, User
from onyx.db.plugin_access import load_user_plugin_states
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import ActionSettings, ApprovalMode, EffectivePolicy
from onyx.integrations.policy import resolve_action_policies, strictest_policies
from onyx.integrations.registry import get_kind_handler
from onyx.tools.interface import Tool
from onyx.tools.models import PluginLinkConfiguration, ToolApprovalScope
from onyx.utils.logger import setup_logger

logger = setup_logger()


class IntegrationChatRequest(BaseModel):
    """The turn values that the tools of an integration need."""

    model_config = ConfigDict(frozen=True)

    persona_id: int
    plugin_links: list[PluginLinkConfiguration]
    approval_mode: ApprovalMode
    chat_session_id: UUID | None = None
    message_id: int | None = None
    additional_headers: dict[str, str] = {}
    mcp_headers: dict[str, str] | None = None


def _plugin_settings(
    db_session: Session, user: User, request: IntegrationChatRequest
) -> list[tuple[UUID, ActionSettings | None]]:
    """The plugins whose integrations the turn uses, with the settings of
    the agent for each."""
    states = load_user_plugin_states([user.id], db_session)
    if user.is_anonymous:
        states = [state for state in states if state.published]
    links = {link.plugin_id: link.action_settings for link in request.plugin_links}
    if request.persona_id == DEFAULT_PERSONA_ID:
        return [
            (state.plugin_id, links.get(state.plugin_id))
            for state in states
            if state.enabled
        ]
    visible = {state.plugin_id for state in states}
    return [
        (link.plugin_id, link.action_settings)
        for link in request.plugin_links
        if link.plugin_id in visible
    ]


def _integration_tools(
    db_session: Session,
    integration: Integration,
    settings: Sequence[ActionSettings | None],
    user: User,
    request: IntegrationChatRequest,
) -> list[Tool]:
    signed_out = user.is_anonymous
    credentials = resolve_call_credentials(
        integration, None if signed_out else user, db_session
    )
    if isinstance(credentials, ConnectionProblem):
        logger.debug(
            "Skipping integration %s: %s", integration.id, credentials.code.value
        )
        return []
    actions = list_integration_actions(integration.id, db_session)
    keys = [action.key for action in actions]
    policies = strictest_policies(
        [
            resolve_action_policies(
                db_session,
                integration=integration,
                action_keys=keys,
                user_id=None if signed_out else user.id,
                link_settings=link_settings,
                approval_mode=request.approval_mode,
                chat_session_id=request.chat_session_id,
            )
            for link_settings in settings
        ]
    )
    offered = [
        action
        for action in actions
        if policies[action.key] is not EffectivePolicy.BLOCKED
    ]
    integration_id = integration.id

    def approval_for(action_key: str) -> ToolApprovalScope | None:
        # Ask is left only in an interactive run.
        if policies.get(action_key) is EffectivePolicy.ASK:
            return ToolApprovalScope(
                integration_id=integration_id, action_id=action_key
            )
        return None

    ctx = ChatToolContext(
        user_id=None if signed_out else user.id,
        user_email=None if signed_out else user.email,
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
    plugin_settings = _plugin_settings(db_session, user, request)
    settings_by_plugin = dict(plugin_settings)
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
