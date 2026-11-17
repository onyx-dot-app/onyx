"""The policy function of integration actions, step by step and in
combination: the admin value (action row, default row, action default, read
only), the lock, the agent or task setting, the user's Always allow, the chat
grant and the approval mode."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.approval_request import create_approval_request__no_commit
from onyx.db.chat import delete_messages_and_files_from_chat_session
from onyx.db.enums import (
    ApprovalDecidedVia,
    ApprovalDecision,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    PluginInstallationPolicy,
)
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatSession,
    Integration,
    IntegrationAction,
    Persona,
    Persona__Plugin,
    User,
    UserPluginPreference,
)
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
    LinkValue,
)
from onyx.integrations.policy import (
    parse_action_settings,
    resolve_action_policies,
    resolve_chat_action_policy,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_persona,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    hold_in_plugin,
    link_persona,
    make_mcp_integration,
    set_policy,
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


class PolicyWorld(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    chat_session_id: UUID
    response_id: int


@pytest.fixture
def world(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    make_test_user: MakeTestUser,
) -> Generator[PolicyWorld, None, None]:
    user = make_test_user("policy_resolution")
    chat_session = ChatSession(id=uuid4(), user_id=user.id, description="policy")
    db_session.add(chat_session)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat_session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.commit()
    chat_session_id, response_id = chat_session.id, response.id
    try:
        yield PolicyWorld(
            user=user, chat_session_id=chat_session_id, response_id=response_id
        )
    finally:
        db_session.rollback()
        delete_messages_and_files_from_chat_session(chat_session_id, db_session)
        db_session.commit()


@pytest.fixture
def integrations(db_session: Session) -> Generator[list[int], None, None]:
    created: list[int] = []
    try:
        yield created
    finally:
        delete_integrations(db_session, created)


def _integration(
    db_session: Session, created: list[int], case: Case, world: PolicyWorld
) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.test/mcp",
        name=f"policy-{uuid4().hex[:8]}",
        tools=(),
        users_can_save_always_allow=case.users_can_save,
    )
    created.append(integration.id)
    db_session.add(
        IntegrationAction(
            integration_id=integration.id,
            key=ACTION,
            source=IntegrationActionSource.MCP,
            display_name=ACTION,
            read_only=case.read_only,
            default_policy=case.action_default,
        )
    )
    db_session.commit()
    for action, value, user_id in (
        (ACTION, case.admin_action, None),
        ("", case.admin_default, None),
        (ACTION, case.user_action, world.user.id),
        ("", case.user_default, world.user.id),
    ):
        if value is not None:
            set_policy(db_session, integration.id, action, value, user_id=user_id)
    if case.chat_grant:
        approval_id = create_approval_request__no_commit(
            db_session,
            chat_session_id=world.chat_session_id,
            chat_message_id=world.response_id,
            integration_id=integration.id,
            action_id=ACTION,
            tool_call_id="call",
            tool_name=ACTION,
            display_name=ACTION,
            arguments={},
        )
        db_session.query(ApprovalRequest).filter(
            ApprovalRequest.id == approval_id
        ).update(
            {
                ApprovalRequest.decision: ApprovalDecision.APPROVED,
                ApprovalRequest.decided_via: ApprovalDecidedVia.SESSION_GRANT,
            }
        )
        db_session.commit()
    return integration


@pytest.mark.parametrize("name", list(CASES))
def test_each_step_of_the_policy_order(
    db_session: Session,
    world: PolicyWorld,
    integrations: list[int],
    name: str,
) -> None:
    case = CASES[name]
    integration = _integration(db_session, integrations, case, world)
    settings = ActionSettings(
        default=case.link_default,
        actions={ACTION: case.link} if case.link is not None else {},
    )

    result = resolve_action_policies(
        db_session,
        integration=integration,
        action_keys=[ACTION],
        user_id=world.user.id,
        link_settings=[settings],
        approval_mode=case.mode,
        chat_session_id=world.chat_session_id,
    )

    assert result == {ACTION: case.expected}


def test_a_caller_with_no_user_gets_no_user_grant_and_no_link_inherits(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    integration = _integration(
        db_session, integrations, Case(user_action=ALLOW, expected=E_ASK), world
    )

    for user_id, expected in ((None, E_ASK), (world.user.id, E_ALLOW)):
        assert resolve_action_policies(
            db_session,
            integration=integration,
            action_keys=[ACTION],
            user_id=user_id,
            link_settings=[],
            approval_mode=ApprovalMode.INTERACTIVE,
            chat_session_id=None,
        ) == {ACTION: expected}


def test_a_chat_grant_applies_only_to_its_chat_and_integration(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    granted = _integration(
        db_session, integrations, Case(chat_grant=True, expected=E_ALLOW), world
    )
    other = _integration(db_session, integrations, Case(expected=E_ASK), world)

    def policy(integration: Integration, chat_session_id: UUID | None) -> str:
        return resolve_action_policies(
            db_session,
            integration=integration,
            action_keys=[ACTION],
            user_id=world.user.id,
            link_settings=[],
            approval_mode=ApprovalMode.INTERACTIVE,
            chat_session_id=chat_session_id,
        )[ACTION].value

    assert policy(granted, world.chat_session_id) == "allow"
    assert policy(granted, uuid4()) == "ask"
    assert policy(granted, None) == "ask"
    assert policy(other, world.chat_session_id) == "ask"


def test_an_unknown_action_key_asks(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    integration = _integration(db_session, integrations, Case(expected=E_ASK), world)

    assert resolve_action_policies(
        db_session,
        integration=integration,
        action_keys=["not_synced"],
        user_id=None,
        link_settings=[],
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    ) == {"not_synced": E_ASK}


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


def _recheck(
    db_session: Session, integration: Integration, user: User, persona_id: int
) -> EffectivePolicy:
    chat_session = ChatSession(
        id=uuid4(), user_id=user.id, persona_id=persona_id, description="recheck"
    )
    db_session.add(chat_session)
    db_session.commit()
    try:
        return resolve_chat_action_policy(
            db_session,
            integration=integration,
            action_key="update",
            user_id=user.id,
            chat_session_id=chat_session.id,
        )
    finally:
        db_session.delete(chat_session)
        db_session.commit()


def test_the_approval_recheck_ignores_plugins_the_user_cannot_use(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    integrations: list[int],
    make_test_user: MakeTestUser,
) -> None:
    """Chat tool construction offers an action through the plugins the user
    can use, so a hidden or turned-off plugin must not block its approval."""
    user = make_test_user("policy_recheck")
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.test/mcp",
        name=f"recheck-{uuid4().hex[:8]}",
        tools=("update",),
    )
    integrations.append(integration.id)
    blocked = {"actions": {"update": "blocked"}}
    visible = hold_in_plugin(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    hidden = hold_in_plugin(
        db_session,
        [integration],
        installation_policy=PluginInstallationPolicy.NOT_AVAILABLE,
    )
    turned_off = hold_in_plugin(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    db_session.add(
        UserPluginPreference(user_id=user.id, plugin_id=turned_off.id, enabled=False)
    )
    db_session.commit()
    persona = create_test_persona(db_session, user)
    try:
        link_persona(db_session, persona.id, visible.id)
        link_persona(db_session, persona.id, hidden.id, blocked)
        link_persona(db_session, DEFAULT_PERSONA_ID, turned_off.id, blocked)

        assert _recheck(db_session, integration, user, persona.id) is (
            EffectivePolicy.ASK
        )
        assert _recheck(db_session, integration, user, DEFAULT_PERSONA_ID) is (
            EffectivePolicy.ASK
        )

        link_persona(db_session, persona.id, turned_off.id, blocked)
        assert _recheck(db_session, integration, user, persona.id) is (
            EffectivePolicy.BLOCKED
        )
    finally:
        db_session.rollback()
        db_session.query(Persona).filter(Persona.id == persona.id).delete()
        db_session.commit()


def test_the_approval_recheck_blocks_when_no_plugin_holds_the_integration(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    integrations: list[int],
    make_test_user: MakeTestUser,
) -> None:
    user = make_test_user("policy_recheck_unheld")
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.test/mcp",
        name=f"unheld-{uuid4().hex[:8]}",
        tools=("update",),
    )
    integrations.append(integration.id)
    plugin = hold_in_plugin(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    persona = create_test_persona(db_session, user)
    try:
        link_persona(db_session, persona.id, plugin.id)
        assert _recheck(db_session, integration, user, persona.id) is (
            EffectivePolicy.ASK
        )

        # The plugin is removed from the agent while an approval waits.
        db_session.query(Persona__Plugin).filter(
            Persona__Plugin.persona_id == persona.id
        ).delete()
        db_session.commit()
        assert _recheck(db_session, integration, user, persona.id) is (
            EffectivePolicy.BLOCKED
        )
    finally:
        db_session.rollback()
        db_session.query(Persona).filter(Persona.id == persona.id).delete()
        db_session.commit()
