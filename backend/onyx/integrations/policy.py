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
from onyx.db.enums import IntegrationActionPolicyValue, PluginInstallationPolicy
from onyx.db.integration import list_integrations_by_ids
from onyx.db.integration_access import load_user_integration_states
from onyx.db.integration_policy import (
    get_chat_session_persona_id,
    get_policy_rows,
    get_session_granted_actions,
    list_in_flight_task_links,
    list_persona_integration_links,
)
from onyx.db.models import Integration, IntegrationAction
from onyx.integrations.actions import integration_actions
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


class AgentIntegration(BaseModel):
    """An integration that an agent uses for a user, with the settings of
    the agent for it."""

    integration: InstanceOf[Integration]
    # The install setting for the user.
    installation_policy: PluginInstallationPolicy
    # The settings of the agent link. The default agent uses an integration
    # with no link; each action then inherits.
    settings: ActionSettings = ActionSettings()
    # A task link of a scheduled run: the owner's saved Always allow choices
    # do not turn its Ask into Allow.
    task_link: bool = False


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
        for action in integration_actions(integration_id, db_session)
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
    link: ActionSettings | None,
    granted: bool,
    approval_mode: ApprovalMode,
) -> EffectivePolicy:
    """The policy of one action from the loaded values. ``action`` is None
    for a key with no stored action. ``link`` is the settings of the agent or
    task link of the integration; None (no link) blocks."""
    if link is None:
        return EffectivePolicy.BLOCKED
    admin = admin_policy(rows.admin, key, action)
    locked = admin is EffectivePolicy.BLOCKED or not users_can_save_always_allow
    policy = _with_link(admin, locked, link.value_for(key))

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
    link_settings: ActionSettings | None,
    approval_mode: ApprovalMode,
    chat_session_id: UUID | None,
    policy_rows: PolicyRows | None = None,
    granted_actions: Collection[str] | None = None,
) -> dict[str, EffectivePolicy]:
    """The policy of each action in ``action_keys`` for one run. ``actions``
    are the stored actions of the integration. ``user_id`` is the acting
    user (None for a caller with no user). ``link_settings`` are the
    settings of the agent or task link of the integration: empty settings
    inherit each action, and None (no link) blocks each action."""
    if not action_keys:
        return {}
    if link_settings is None:
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
    return {
        key: decide_action_policy(
            key,
            by_key.get(key),
            rows,
            users_can_save_always_allow=integration.users_can_save_always_allow,
            link=link_settings,
            granted=key in granted,
            approval_mode=approval_mode,
        )
        for key in action_keys
    }


def agent_link_settings_by_integration(
    db_session: Session,
    user_id: UUID,
    persona_id: int,
    links: Mapping[int, ActionSettings],
    *,
    for_everyone_only: bool = False,
) -> dict[int, AgentIntegration]:
    """Each integration that a chat of the agent uses for the user, in
    integration order, with the settings of the agent for it. ``links`` are
    the settings of the agent links by integration id. The default agent uses
    each integration that the user turned on; a link only gives it settings.
    Another agent uses each integration of its links that the user has
    access to: the user's on/off choice does not apply. ``for_everyone_only``
    keeps only the integrations that each user has."""
    return linked_integrations(
        db_session,
        user_id,
        links,
        all_turned_on=persona_id == DEFAULT_PERSONA_ID,
        for_everyone_only=for_everyone_only,
    )


def linked_integrations(
    db_session: Session,
    user_id: UUID,
    links: Mapping[int, ActionSettings],
    *,
    all_turned_on: bool,
    for_everyone_only: bool = False,
    task_link: bool = False,
) -> dict[int, AgentIntegration]:
    """``all_turned_on``: each integration the user turned on, with the
    settings of its link. Otherwise each linked integration the user has
    access to, turned on or not."""
    states = {
        state.integration_id: state
        for state in load_user_integration_states(
            [user_id], db_session, None if all_turned_on else list(links)
        )
        if (state.turned_on or not all_turned_on)
        and (state.for_everyone or not for_everyone_only)
    }
    return {
        integration.id: AgentIntegration(
            integration=integration,
            installation_policy=states[integration.id].installation_policy,
            settings=links.get(integration.id, ActionSettings()),
            task_link=task_link,
        )
        for integration in list_integrations_by_ids(list(states), db_session)
    }


def agent_integration_ids(
    db_session: Session,
    user_id: UUID,
    persona_id: int,
    links: Mapping[int, ActionSettings],
    *,
    for_everyone_only: bool = False,
) -> list[int]:
    """The ids of the integrations of ``agent_link_settings_by_integration``,
    in order. Tool options name an integration by its id."""
    return sorted(
        agent_link_settings_by_integration(
            db_session,
            user_id,
            persona_id,
            links,
            for_everyone_only=for_everyone_only,
        )
    )


def chat_integrations(
    db_session: Session,
    user_id: UUID,
    persona_id: int,
    persona_links: Mapping[int, ActionSettings],
    chat_session_id: UUID | None,
    *,
    for_everyone_only: bool = False,
) -> dict[int, AgentIntegration]:
    """The integrations a chat can use. While a scheduled run is in flight in
    the chat, these are the task's integrations with the task's settings.
    The task's authority ends with the run; later turns use the agent."""
    task_links = (
        list_in_flight_task_links(db_session, chat_session_id)
        if chat_session_id is not None
        else None
    )
    if task_links is not None:
        return linked_integrations(
            db_session,
            user_id,
            {
                link.integration_id: parse_action_settings(link.action_settings)
                for link in task_links
            },
            all_turned_on=False,
            for_everyone_only=for_everyone_only,
            task_link=True,
        )
    return agent_link_settings_by_integration(
        db_session,
        user_id,
        persona_id,
        persona_links,
        for_everyone_only=for_everyone_only,
    )


def persona_link_settings(
    db_session: Session, persona_id: int
) -> dict[int, ActionSettings]:
    """The settings of each integration link of the agent."""
    return {
        link.integration_id: parse_action_settings(link.action_settings)
        for link in list_persona_integration_links(db_session, persona_id)
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
    Blocked now. It reads the integrations that chat tool construction reads,
    so an integration the user cannot use on the agent is Blocked."""
    persona_id = get_chat_session_persona_id(db_session, chat_session_id)
    held = (
        chat_integrations(
            db_session,
            user_id,
            persona_id,
            persona_link_settings(db_session, persona_id),
            chat_session_id,
        ).get(integration.id)
        if persona_id is not None
        else None
    )
    return resolve_action_policies(
        db_session,
        integration=integration,
        actions=integration_actions(integration.id, db_session),
        action_keys=[action_key],
        user_id=None if held is not None and held.task_link else user_id,
        link_settings=held.settings if held is not None else None,
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    )[action_key]
