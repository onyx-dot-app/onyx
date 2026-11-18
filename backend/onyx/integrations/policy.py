"""The one policy function for integration actions. Chat tool construction,
the chat approval check and the sandbox proxy call it.

The order, for each action:

1. The admin value: the admin row of the action, else the admin default row,
   else the default of the action, else Allow for a read-only action and Ask
   for each other one. Auto counts as Ask.
2. The admin value is locked when it is Blocked, or when users cannot save
   Always allow on the integration.
3. The setting of the agent or the task: Blocked blocks; Ask asks unless the
   admin blocks; Allow allows unless locked; Inherit keeps the admin value.
4. The user's saved Always allow turns Ask into Allow, unless locked.
5. "Approve for this chat" turns Ask into Allow. It never changes Blocked.
6. With no approver, Ask is Blocked. In a run without questions, Ask runs.
"""

from collections.abc import Collection, Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, InstanceOf, ValidationError
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.enums import IntegrationActionPolicyValue
from onyx.db.integration import list_integration_actions
from onyx.db.integration_policy import (
    get_chat_session_persona_id,
    get_policy_rows,
    get_session_granted_actions,
    list_persona_plugin_links,
    list_plugin_integrations,
)
from onyx.db.models import Integration, IntegrationAction
from onyx.db.plugin_access import load_user_plugin_states
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
    LinkValue,
    PolicyRows,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The empty action key names the default row.
DEFAULT_ACTION_KEY = ""

STORED_TO_EFFECTIVE: dict[IntegrationActionPolicyValue, EffectivePolicy] = {
    IntegrationActionPolicyValue.ALLOW: EffectivePolicy.ALLOW,
    # No run mode answers Auto yet.
    IntegrationActionPolicyValue.AUTO: EffectivePolicy.ASK,
    IntegrationActionPolicyValue.ASK: EffectivePolicy.ASK,
    IntegrationActionPolicyValue.BLOCKED: EffectivePolicy.BLOCKED,
}

_STRICTNESS: dict[EffectivePolicy, int] = {
    EffectivePolicy.ALLOW: 0,
    EffectivePolicy.ASK: 1,
    EffectivePolicy.BLOCKED: 2,
}


class AgentIntegrationLinks(BaseModel):
    """An integration that plugins of an agent hold, with each such plugin
    and its agent settings."""

    integration: InstanceOf[Integration]
    plugin_ids: list[UUID] = []
    settings: list[ActionSettings | None] = []


def parse_action_settings(raw: Mapping[str, object] | None) -> ActionSettings:
    """The stored settings of a link. A value that does not parse blocks
    each action of the link, so a bad row never opens an action."""
    if not raw:
        return ActionSettings()
    try:
        return ActionSettings.model_validate(raw)
    except ValidationError:
        logger.warning("Invalid action_settings %s; blocking the link", raw)
        return ActionSettings(default=LinkValue.BLOCKED)


def action_default_policy(action: IntegrationAction | None) -> EffectivePolicy:
    if action is None:
        return EffectivePolicy.ASK
    if action.default_policy is not None:
        return STORED_TO_EFFECTIVE[action.default_policy]
    return EffectivePolicy.ALLOW if action.read_only else EffectivePolicy.ASK


def admin_policy(
    admin_rows: Mapping[str, IntegrationActionPolicyValue],
    action_key: str,
    action: IntegrationAction | None,
) -> EffectivePolicy:
    """Step 1: the admin row of the action, else the admin default row, else
    the default of the action."""
    stored = admin_rows.get(action_key, admin_rows.get(DEFAULT_ACTION_KEY))
    if stored is not None:
        return STORED_TO_EFFECTIVE[stored]
    return action_default_policy(action)


def admin_blocked_actions(db_session: Session, integration_id: int) -> set[str]:
    """The actions whose admin value (step 1) is Blocked."""
    rows = get_policy_rows(db_session, integration_id, None).admin
    return {
        action.key
        for action in list_integration_actions(integration_id, db_session)
        if admin_policy(rows, action.key, action) is EffectivePolicy.BLOCKED
    }


def _with_link(
    admin: EffectivePolicy, locked: bool, link: LinkValue
) -> EffectivePolicy:
    if link is LinkValue.BLOCKED:
        return EffectivePolicy.BLOCKED
    if link is LinkValue.ASK:
        return (
            EffectivePolicy.BLOCKED
            if admin is EffectivePolicy.BLOCKED
            else EffectivePolicy.ASK
        )
    if link is LinkValue.ALLOW:
        return admin if locked else EffectivePolicy.ALLOW
    return admin


def decide_action_policy(
    key: str,
    action: IntegrationAction | None,
    rows: PolicyRows,
    *,
    users_can_save_always_allow: bool,
    links: Sequence[ActionSettings],
    granted: bool,
    approval_mode: ApprovalMode,
) -> EffectivePolicy:
    """The policy of one action from the loaded values. ``action`` is None
    for a key with no stored action. ``links`` are the settings of each link
    that holds the integration; the strictest link wins, and no link
    blocks."""
    if not links:
        return EffectivePolicy.BLOCKED
    admin = admin_policy(rows.admin, key, action)
    locked = admin is EffectivePolicy.BLOCKED or not users_can_save_always_allow
    policy = max(
        (_with_link(admin, locked, link.value_for(key)) for link in links),
        key=_STRICTNESS.__getitem__,
    )

    if policy is EffectivePolicy.ASK and not locked:
        user_value = rows.user.get(key, rows.user.get(DEFAULT_ACTION_KEY))
        if user_value is IntegrationActionPolicyValue.ALLOW:
            policy = EffectivePolicy.ALLOW
    if policy is EffectivePolicy.ASK and granted:
        policy = EffectivePolicy.ALLOW

    if policy is EffectivePolicy.ASK:
        if approval_mode is ApprovalMode.NO_APPROVER:
            return EffectivePolicy.BLOCKED
        if approval_mode is ApprovalMode.RUN_WITHOUT_ASKING:
            return EffectivePolicy.ALLOW
    return policy


def resolve_action_policies(
    db_session: Session,
    *,
    integration: Integration,
    actions: Sequence[IntegrationAction],
    action_keys: Collection[str],
    user_id: UUID | None,
    link_settings: Sequence[ActionSettings | None],
    approval_mode: ApprovalMode,
    chat_session_id: UUID | None,
    policy_rows: PolicyRows | None = None,
    granted_actions: Collection[str] | None = None,
) -> dict[str, EffectivePolicy]:
    """The policy of each action in ``action_keys`` for one run. ``actions``
    are the stored actions of the integration. ``user_id`` is the acting
    user (None for a caller with no user). ``link_settings`` are the
    settings of each agent or task link that holds the integration: None
    inherits each action, and an empty list blocks each action."""
    if not action_keys:
        return {}
    if not link_settings:
        return dict.fromkeys(action_keys, EffectivePolicy.BLOCKED)
    by_key = {action.key: action for action in actions}
    rows = (
        policy_rows
        if policy_rows is not None
        else get_policy_rows(db_session, integration.id, user_id)
    )
    granted = (
        granted_actions
        if granted_actions is not None
        else (
            get_session_granted_actions(db_session, chat_session_id, integration.id)
            if chat_session_id is not None
            else set()
        )
    )
    links = [settings or ActionSettings() for settings in link_settings]
    return {
        key: decide_action_policy(
            key,
            by_key.get(key),
            rows,
            users_can_save_always_allow=integration.users_can_save_always_allow,
            links=links,
            granted=key in granted,
            approval_mode=approval_mode,
        )
        for key in action_keys
    }


def agent_plugin_settings(
    db_session: Session,
    user_id: UUID,
    persona_id: int,
    links: Mapping[UUID, ActionSettings],
    *,
    published_only: bool = False,
) -> dict[UUID, ActionSettings | None]:
    """The plugins whose integrations a chat of the agent uses, with the
    settings of the agent for each. The default agent uses each plugin the
    user runs; another agent uses each linked plugin the user can see.
    ``published_only`` keeps only the Organization library."""
    states = load_user_plugin_states(
        [user_id],
        db_session,
        plugin_ids=None if persona_id == DEFAULT_PERSONA_ID else list(links),
    )
    if published_only:
        states = [state for state in states if state.published]
    if persona_id == DEFAULT_PERSONA_ID:
        return {
            state.plugin_id: links.get(state.plugin_id)
            for state in states
            if state.enabled
        }
    visible = {state.plugin_id for state in states}
    return {
        plugin_id: settings
        for plugin_id, settings in links.items()
        if plugin_id in visible
    }


def agent_link_settings_by_integration(
    db_session: Session,
    user_id: UUID,
    persona_id: int,
    links: Mapping[UUID, ActionSettings],
    *,
    published_only: bool = False,
) -> dict[int, AgentIntegrationLinks]:
    """Each integration that a plugin from ``agent_plugin_settings`` holds,
    with the agent settings of each such plugin, in integration order."""
    settings_by_plugin = agent_plugin_settings(
        db_session, user_id, persona_id, links, published_only=published_only
    )
    by_integration: dict[int, AgentIntegrationLinks] = {}
    for plugin_id, integration in list_plugin_integrations(
        db_session, list(settings_by_plugin)
    ):
        held = by_integration.setdefault(
            integration.id, AgentIntegrationLinks(integration=integration)
        )
        held.plugin_ids.append(plugin_id)
        held.settings.append(settings_by_plugin[plugin_id])
    return by_integration


def resolve_chat_action_policy(
    db_session: Session,
    *,
    integration: Integration,
    action_key: str,
    user_id: UUID,
    chat_session_id: UUID,
) -> EffectivePolicy:
    """The current policy of one action for the agent of a chat, before the
    chat grants. The approval check uses it to see that an action is not
    Blocked now. It reads the plugins that chat tool construction reads, so
    a plugin the user cannot use does not change the result, and an action
    that no such plugin holds is Blocked."""
    persona_id = get_chat_session_persona_id(db_session, chat_session_id)
    held = (
        agent_link_settings_by_integration(
            db_session,
            user_id,
            persona_id,
            {
                link.plugin_id: parse_action_settings(link.action_settings)
                for link in list_persona_plugin_links(db_session, persona_id)
            },
        ).get(integration.id)
        if persona_id is not None
        else None
    )
    return resolve_action_policies(
        db_session,
        integration=integration,
        actions=list_integration_actions(integration.id, db_session),
        action_keys=[action_key],
        user_id=user_id,
        link_settings=held.settings if held is not None else [],
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    )[action_key]
