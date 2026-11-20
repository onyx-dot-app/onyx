"""The loads of the policy function of integration actions: the stored
action, the admin and user rows, the chat grants and the agent links of the
approval recheck. ``tests/unit/onyx/integrations/test_decide_action_policy.py``
covers the policy order on loaded values."""

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
from onyx.db.integration import list_integration_actions
from onyx.db.integration_policy import (
    list_policy_rows,
    list_session_granted_actions,
)
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatSession,
    Integration,
    IntegrationAction,
    Persona,
    Persona__Integration,
    User,
    UserIntegrationPreference,
)
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
)
from onyx.integrations.policy import (
    resolve_action_policies,
    resolve_chat_action_policy,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_persona,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    link_persona,
    make_mcp_integration,
    set_policy,
)

ALLOW = IntegrationActionPolicyValue.ALLOW
ASK = IntegrationActionPolicyValue.ASK
BLOCKED = IntegrationActionPolicyValue.BLOCKED
ACTION = "send"
E_ALLOW = EffectivePolicy.ALLOW
E_ASK = EffectivePolicy.ASK
E_BLOCKED = EffectivePolicy.BLOCKED


class Rows(BaseModel):
    model_config = ConfigDict(frozen=True)

    read_only: bool | None = None
    admin_action: IntegrationActionPolicyValue | None = None
    admin_default: IntegrationActionPolicyValue | None = None
    user_action: IntegrationActionPolicyValue | None = None
    chat_grant: bool = False


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
    db_session: Session, created: list[int], rows: Rows, world: PolicyWorld
) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.test/mcp",
        name=f"policy-{uuid4().hex[:8]}",
        tools=(),
    )
    created.append(integration.id)
    db_session.add(
        IntegrationAction(
            integration_id=integration.id,
            key=ACTION,
            source=IntegrationActionSource.MCP,
            display_name=ACTION,
            read_only=rows.read_only,
        )
    )
    db_session.commit()
    for action, value, user_id in (
        (ACTION, rows.admin_action, None),
        ("", rows.admin_default, None),
        (ACTION, rows.user_action, world.user.id),
    ):
        if value is not None:
            set_policy(db_session, integration.id, action, value, user_id=user_id)
    if rows.chat_grant:
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


def _resolve(
    db_session: Session,
    integration: Integration,
    *,
    user_id: UUID | None,
    chat_session_id: UUID | None = None,
    action_key: str = ACTION,
    linked: bool = True,
) -> EffectivePolicy:
    return resolve_action_policies(
        db_session,
        integration=integration,
        actions=list_integration_actions(integration.id, db_session),
        action_keys=[action_key],
        user_id=user_id,
        link_settings=ActionSettings() if linked else None,
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=chat_session_id,
    )[action_key]


def test_bulk_reads_of_no_integration_or_no_chat_are_empty(
    world: PolicyWorld, integrations: list[int], db_session: Session
) -> None:
    assert list_policy_rows(db_session, [], world.user.id) == {}
    assert list_session_granted_actions(db_session, None, integrations) == {
        key: set() for key in integrations
    }


def test_the_stored_action_and_the_admin_rows_give_the_admin_value(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    read_only = _integration(db_session, integrations, Rows(read_only=True), world)
    default_row = _integration(
        db_session, integrations, Rows(read_only=True, admin_default=BLOCKED), world
    )
    action_row = _integration(
        db_session,
        integrations,
        Rows(admin_default=BLOCKED, admin_action=ALLOW),
        world,
    )

    assert _resolve(db_session, read_only, user_id=None) is E_ALLOW
    assert _resolve(db_session, default_row, user_id=None) is E_BLOCKED
    assert _resolve(db_session, action_row, user_id=None) is E_ALLOW


def test_the_user_row_applies_only_to_its_user(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    integration = _integration(db_session, integrations, Rows(user_action=ALLOW), world)

    assert _resolve(db_session, integration, user_id=None) is E_ASK
    assert _resolve(db_session, integration, user_id=uuid4()) is E_ASK
    assert _resolve(db_session, integration, user_id=world.user.id) is E_ALLOW


def test_a_chat_grant_applies_only_to_its_chat_and_integration(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    granted = _integration(db_session, integrations, Rows(chat_grant=True), world)
    other = _integration(db_session, integrations, Rows(), world)

    def policy(integration: Integration, chat_session_id: UUID | None) -> str:
        return _resolve(
            db_session,
            integration,
            user_id=world.user.id,
            chat_session_id=chat_session_id,
        ).value

    assert policy(granted, world.chat_session_id) == "allow"
    assert policy(granted, uuid4()) == "ask"
    assert policy(granted, None) == "ask"
    assert policy(other, world.chat_session_id) == "ask"


def test_an_unknown_action_key_asks_and_no_link_blocks(
    db_session: Session, world: PolicyWorld, integrations: list[int]
) -> None:
    integration = _integration(db_session, integrations, Rows(), world)

    assert _resolve(db_session, integration, user_id=None, action_key="x") is E_ASK
    assert _resolve(db_session, integration, user_id=None, linked=False) is E_BLOCKED


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


def test_the_approval_recheck_reads_the_integrations_the_user_can_use(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    integrations: list[int],
    make_test_user: MakeTestUser,
) -> None:
    """Chat tool construction offers an action of an integration that the
    user can use on the agent, so the approval check reads the same
    integrations: the user's on/off choice counts only on the default agent,
    and an integration with no access is Blocked."""
    user = make_test_user("policy_recheck")

    def integration_with(policy: PluginInstallationPolicy) -> Integration:
        integration, _ = make_mcp_integration(
            db_session,
            server_url="https://mcp.example.test/mcp",
            name=f"recheck-{uuid4().hex[:8]}",
            tools=("update",),
        )
        integrations.append(integration.id)
        give_access(db_session, [integration], installation_policy=policy)
        return integration

    turned_off = integration_with(PluginInstallationPolicy.DEFAULT)
    no_access = integration_with(PluginInstallationPolicy.NOT_AVAILABLE)
    db_session.add(
        UserIntegrationPreference(
            user_id=user.id, integration_id=turned_off.id, enabled=False
        )
    )
    db_session.commit()
    persona = create_test_persona(db_session, user)
    try:
        link_persona(db_session, persona.id, turned_off.id)
        link_persona(db_session, persona.id, no_access.id)

        assert _recheck(db_session, turned_off, user, persona.id) is (
            EffectivePolicy.ASK
        )
        assert _recheck(db_session, turned_off, user, DEFAULT_PERSONA_ID) is (
            EffectivePolicy.BLOCKED
        )
        assert _recheck(db_session, no_access, user, persona.id) is (
            EffectivePolicy.BLOCKED
        )
    finally:
        db_session.rollback()
        db_session.query(Persona).filter(Persona.id == persona.id).delete()
        db_session.commit()


def test_the_approval_recheck_blocks_when_the_agent_has_no_link(
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
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    persona = create_test_persona(db_session, user)
    try:
        link_persona(db_session, persona.id, integration.id)
        assert _recheck(db_session, integration, user, persona.id) is (
            EffectivePolicy.ASK
        )

        # The integration is removed from the agent while an approval waits.
        db_session.query(Persona__Integration).filter(
            Persona__Integration.persona_id == persona.id
        ).delete()
        db_session.commit()
        assert _recheck(db_session, integration, user, persona.id) is (
            EffectivePolicy.BLOCKED
        )
    finally:
        db_session.rollback()
        db_session.query(Persona).filter(Persona.id == persona.id).delete()
        db_session.commit()
