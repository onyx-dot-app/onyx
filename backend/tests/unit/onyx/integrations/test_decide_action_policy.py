"""The policy order of integration actions on loaded values: the admin value
(action row, default row, action default, read only), the lock, the agent or
task setting, the user's Always allow, the chat grant and the approval mode."""

import pytest
from pydantic import BaseModel, ConfigDict

from onyx.db.enums import IntegrationActionPolicyValue, IntegrationActionSource
from onyx.db.models import IntegrationAction
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
    LinkValue,
    PolicyRows,
)
from onyx.integrations.policy import (
    DEFAULT_ACTION_KEY,
    decide_action_policy,
    parse_action_settings,
)

ALLOW = IntegrationActionPolicyValue.ALLOW
AUTO = IntegrationActionPolicyValue.AUTO
ASK = IntegrationActionPolicyValue.ASK
BLOCKED = IntegrationActionPolicyValue.BLOCKED
ACTION = "send"


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Step 1
    admin_action: IntegrationActionPolicyValue | None = None
    admin_default: IntegrationActionPolicyValue | None = None
    action_default: IntegrationActionPolicyValue | None = None
    read_only: bool | None = None
    # Step 2
    users_can_save: bool = True
    # Step 3
    link: LinkValue | None = None
    link_default: LinkValue = LinkValue.INHERIT
    # Step 4
    user_action: IntegrationActionPolicyValue | None = None
    user_default: IntegrationActionPolicyValue | None = None
    # Step 5
    chat_grant: bool = False
    # Step 6
    mode: ApprovalMode = ApprovalMode.INTERACTIVE
    expected: EffectivePolicy


NO = ApprovalMode.NO_APPROVER
RUN = ApprovalMode.RUN_WITHOUT_ASKING
E_ALLOW = EffectivePolicy.ALLOW
E_ASK = EffectivePolicy.ASK
E_BLOCKED = EffectivePolicy.BLOCKED

CASES: dict[str, Case] = {
    # Step 1: where the admin value comes from.
    "no rows, not read only: ask": Case(expected=E_ASK),
    "no rows, read only: allow": Case(read_only=True, expected=E_ALLOW),
    "action default wins over read only": Case(
        read_only=True, action_default=ASK, expected=E_ASK
    ),
    "action default allow": Case(action_default=ALLOW, expected=E_ALLOW),
    "admin default row wins over action default": Case(
        action_default=ALLOW, admin_default=ASK, expected=E_ASK
    ),
    "admin action row wins over default row": Case(
        admin_default=BLOCKED, admin_action=ALLOW, expected=E_ALLOW
    ),
    "admin blocked": Case(admin_action=BLOCKED, expected=E_BLOCKED),
    "auto counts as ask": Case(admin_action=AUTO, expected=E_ASK),
    "auto action default counts as ask": Case(action_default=AUTO, expected=E_ASK),
    # Step 3: the link setting.
    "link blocked over admin allow": Case(
        admin_action=ALLOW, link=LinkValue.BLOCKED, expected=E_BLOCKED
    ),
    "link ask over admin allow": Case(
        admin_action=ALLOW, link=LinkValue.ASK, expected=E_ASK
    ),
    "link ask keeps admin blocked": Case(
        admin_action=BLOCKED, link=LinkValue.ASK, expected=E_BLOCKED
    ),
    "link allow over admin ask": Case(
        admin_action=ASK, link=LinkValue.ALLOW, expected=E_ALLOW
    ),
    "link allow cannot open admin blocked": Case(
        admin_action=BLOCKED, link=LinkValue.ALLOW, expected=E_BLOCKED
    ),
    "link allow locked by users_can_save": Case(
        admin_action=ASK, users_can_save=False, link=LinkValue.ALLOW, expected=E_ASK
    ),
    "link inherit keeps admin": Case(
        admin_action=ALLOW, link=LinkValue.INHERIT, expected=E_ALLOW
    ),
    "link default applies to an action with no setting": Case(
        admin_action=ALLOW, link_default=LinkValue.BLOCKED, expected=E_BLOCKED
    ),
    "link action setting wins over link default": Case(
        admin_action=ASK,
        link_default=LinkValue.BLOCKED,
        link=LinkValue.ALLOW,
        expected=E_ALLOW,
    ),
    # Step 4: the user's saved grant.
    "user action allow turns ask into allow": Case(user_action=ALLOW, expected=E_ALLOW),
    "user default allow turns ask into allow": Case(
        user_default=ALLOW, expected=E_ALLOW
    ),
    "user action row wins over user default": Case(
        user_action=ASK, user_default=ALLOW, expected=E_ASK
    ),
    "user grant overrides link ask": Case(
        link=LinkValue.ASK, user_action=ALLOW, expected=E_ALLOW
    ),
    "user grant locked by users_can_save": Case(
        users_can_save=False, user_action=ALLOW, expected=E_ASK
    ),
    "user grant never opens admin blocked": Case(
        admin_action=BLOCKED, user_action=ALLOW, expected=E_BLOCKED
    ),
    "user grant never opens link blocked": Case(
        link=LinkValue.BLOCKED, user_action=ALLOW, expected=E_BLOCKED
    ),
    # Step 5: "Approve for this chat".
    "chat grant turns ask into allow": Case(chat_grant=True, expected=E_ALLOW),
    "chat grant applies when locked": Case(
        users_can_save=False, chat_grant=True, expected=E_ALLOW
    ),
    "chat grant never opens admin blocked": Case(
        admin_action=BLOCKED, chat_grant=True, expected=E_BLOCKED
    ),
    "chat grant never opens link blocked": Case(
        link=LinkValue.BLOCKED, chat_grant=True, expected=E_BLOCKED
    ),
    # Step 6: the approval mode.
    "no approver blocks ask": Case(mode=NO, expected=E_BLOCKED),
    "no approver keeps allow": Case(admin_action=ALLOW, mode=NO, expected=E_ALLOW),
    "no approver with link allow runs (bot freeze)": Case(
        link=LinkValue.ALLOW, mode=NO, expected=E_ALLOW
    ),
    "no approver after a user grant runs": Case(
        user_action=ALLOW, mode=NO, expected=E_ALLOW
    ),
    "run without asking runs ask": Case(mode=RUN, expected=E_ALLOW),
    "run without asking keeps blocked": Case(
        admin_action=BLOCKED, mode=RUN, expected=E_BLOCKED
    ),
    "run without asking keeps link blocked": Case(
        link=LinkValue.BLOCKED, mode=RUN, expected=E_BLOCKED
    ),
}


def _rows(
    action: IntegrationActionPolicyValue | None,
    default: IntegrationActionPolicyValue | None,
) -> dict[str, IntegrationActionPolicyValue]:
    return {
        key: value
        for key, value in ((ACTION, action), (DEFAULT_ACTION_KEY, default))
        if value is not None
    }


@pytest.mark.parametrize("name", list(CASES))
def test_each_step_of_the_policy_order(name: str) -> None:
    case = CASES[name]
    action = IntegrationAction(
        key=ACTION,
        source=IntegrationActionSource.MCP,
        display_name=ACTION,
        read_only=case.read_only,
        default_policy=case.action_default,
    )
    link = ActionSettings(
        default=case.link_default,
        actions={ACTION: case.link} if case.link is not None else {},
    )

    result = decide_action_policy(
        ACTION,
        action,
        PolicyRows(
            admin=_rows(case.admin_action, case.admin_default),
            user=_rows(case.user_action, case.user_default),
        ),
        users_can_save_always_allow=case.users_can_save,
        link=link,
        granted=case.chat_grant,
        approval_mode=case.mode,
    )

    assert result is case.expected


def _decide(
    action: IntegrationAction | None, link: ActionSettings | None
) -> EffectivePolicy:
    return decide_action_policy(
        ACTION,
        action,
        PolicyRows(admin={}, user={}),
        users_can_save_always_allow=True,
        link=link,
        granted=False,
        approval_mode=ApprovalMode.INTERACTIVE,
    )


def test_an_action_with_no_stored_row_asks() -> None:
    assert _decide(None, ActionSettings()) is E_ASK


def test_no_link_blocks() -> None:
    assert _decide(None, None) is E_BLOCKED


def test_stored_settings_parse_and_a_bad_row_blocks() -> None:
    assert parse_action_settings({}) == ActionSettings()
    assert parse_action_settings(
        {"default": "blocked", "actions": {"a": "inherit", "b": "allow"}}
    ) == ActionSettings(
        default=LinkValue.BLOCKED,
        actions={"a": LinkValue.INHERIT, "b": LinkValue.ALLOW},
    )
    assert parse_action_settings({"default": "sometimes"}) == ActionSettings(
        default=LinkValue.BLOCKED
    )
