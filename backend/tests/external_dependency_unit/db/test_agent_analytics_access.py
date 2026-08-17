"""Who may read an agent's analytics: a global MANAGE_AGENTS holder reads any, everyone
else only agents they own, and the token is required either way. The route's GATE 2
delegates to the projection the UI reads, so asserting one asserts both."""

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.analytics import user_can_view_assistant_stats
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.persona import can_view_persona_stats
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona

# The gate under test is MIT-computable, so EE mode changes nothing here — pinned so the
# EE entry point is exercised in the mode it runs in, not whatever a neighbour left set.
pytestmark = pytest.mark.usefixtures("enable_ee")


def _grant(user: User, *permissions: Permission) -> None:
    """Set effective_permissions directly — group plumbing is covered elsewhere."""
    user.effective_permissions = [p.value for p in permissions]


def test_admin_reads_any_agents_analytics(db_session: Session) -> None:
    admin = create_test_user(db_session, "analytics_admin", is_admin=True)
    owner = create_test_user(db_session, "analytics_owner")
    persona = create_test_persona(db_session, owner)

    assert user_can_view_assistant_stats(db_session, admin, persona.id)


def test_manage_agents_holder_reads_any_agents_analytics(db_session: Session) -> None:
    manager = create_test_user(db_session, "analytics_manager")
    _grant(manager, Permission.MANAGE_AGENTS)
    owner = create_test_user(db_session, "analytics_owner")
    persona = create_test_persona(db_session, owner)

    # MANAGE_AGENTS implies the analytics token, so no second grant is needed.
    assert user_can_view_assistant_stats(db_session, manager, persona.id)


def test_holder_reads_only_its_own_agents_analytics(db_session: Session) -> None:
    owner = create_test_user(db_session, "analytics_owner")
    _grant(owner, Permission.READ_AGENT_ANALYTICS)
    stranger = create_test_user(db_session, "analytics_stranger")
    _grant(stranger, Permission.READ_AGENT_ANALYTICS)
    persona = create_test_persona(db_session, owner)

    assert user_can_view_assistant_stats(db_session, owner, persona.id)
    assert not user_can_view_assistant_stats(db_session, stranger, persona.id)


def test_owner_without_the_token_is_refused(db_session: Session) -> None:
    owner = create_test_user(db_session, "analytics_owner")
    _grant(owner)
    persona = create_test_persona(db_session, owner)

    assert not user_can_view_assistant_stats(db_session, owner, persona.id)


def test_projection_matches_the_gate(db_session: Session) -> None:
    # The UI must not offer an affordance the route would refuse.
    admin = create_test_user(db_session, "analytics_admin", is_admin=True)
    owner = create_test_user(db_session, "analytics_owner")
    _grant(owner, Permission.READ_AGENT_ANALYTICS)
    stranger = create_test_user(db_session, "analytics_stranger")
    _grant(stranger, Permission.READ_AGENT_ANALYTICS)
    persona = create_test_persona(db_session, owner)

    for actor in (admin, owner, stranger):
        assert can_view_persona_stats(
            actor, persona, db_session
        ) == user_can_view_assistant_stats(db_session, actor, persona.id), actor.email
