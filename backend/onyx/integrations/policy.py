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

from pydantic import ValidationError
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
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The empty action key names the default row.
DEFAULT_ACTION_KEY = ""

_STORED_TO_EFFECTIVE: dict[IntegrationActionPolicyValue, EffectivePolicy] = {
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


def _action_default(action: IntegrationAction | None) -> EffectivePolicy:
    if action is None:
        return EffectivePolicy.ASK
    if action.default_policy is not None:
        return _STORED_TO_EFFECTIVE[action.default_policy]
    return EffectivePolicy.ALLOW if action.read_only else EffectivePolicy.ASK


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


def resolve_action_policies(
    db_session: Session,
    *,
    integration: Integration,
    action_keys: Collection[str],
    user_id: UUID | None,
    link_settings: Sequence[ActionSettings | None],
    approval_mode: ApprovalMode,
    chat_session_id: UUID | None,
) -> dict[str, EffectivePolicy]:
    """The policy of each action in ``action_keys`` for one run. ``user_id``
    is the acting user (None for a caller with no user). ``link_settings``
    are the settings of each agent or task link that holds the integration;
    the strictest link wins, and None or no link inherits each action."""
    if not action_keys:
        return {}
    actions = {
        action.key: action
        for action in list_integration_actions(integration.id, db_session)
    }
    rows = get_policy_rows(db_session, integration.id, user_id)
    granted = (
        get_session_granted_actions(db_session, chat_session_id, integration.id)
        if chat_session_id is not None
        else set()
    )
    links = [settings or ActionSettings() for settings in link_settings or [None]]

    policies: dict[str, EffectivePolicy] = {}
    for key in action_keys:
        stored_admin = rows.admin.get(key, rows.admin.get(DEFAULT_ACTION_KEY))
        admin = (
            _STORED_TO_EFFECTIVE[stored_admin]
            if stored_admin is not None
            else _action_default(actions.get(key))
        )
        locked = (
            admin is EffectivePolicy.BLOCKED
            or not integration.users_can_save_always_allow
        )
        policy = max(
            (_with_link(admin, locked, link.value_for(key)) for link in links),
            key=_STRICTNESS.__getitem__,
        )

        if policy is EffectivePolicy.ASK and not locked:
            user_value = rows.user.get(key, rows.user.get(DEFAULT_ACTION_KEY))
            if user_value is IntegrationActionPolicyValue.ALLOW:
                policy = EffectivePolicy.ALLOW
        if policy is EffectivePolicy.ASK and key in granted:
            policy = EffectivePolicy.ALLOW

        if policy is EffectivePolicy.ASK:
            if approval_mode is ApprovalMode.NO_APPROVER:
                policy = EffectivePolicy.BLOCKED
            elif approval_mode is ApprovalMode.RUN_WITHOUT_ASKING:
                policy = EffectivePolicy.ALLOW
        policies[key] = policy
    return policies


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
    states = load_user_plugin_states([user_id], db_session)
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
    a plugin the user cannot use does not change the result."""
    persona_id = get_chat_session_persona_id(db_session, chat_session_id)
    link_settings: list[ActionSettings | None] = []
    if persona_id is not None:
        settings_by_plugin = agent_plugin_settings(
            db_session,
            user_id,
            persona_id,
            {
                link.plugin_id: parse_action_settings(link.action_settings)
                for link in list_persona_plugin_links(db_session, persona_id)
            },
        )
        link_settings = [
            settings_by_plugin[plugin_id]
            for plugin_id, held in list_plugin_integrations(
                db_session, list(settings_by_plugin)
            )
            if held.id == integration.id
        ]
    return resolve_action_policies(
        db_session,
        integration=integration,
        action_keys=[action_key],
        user_id=user_id,
        link_settings=link_settings,
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    )[action_key]
