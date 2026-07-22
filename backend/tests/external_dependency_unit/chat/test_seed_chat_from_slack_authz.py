"""Authorization tests for the Slack chat-seed copy path.

Regression coverage for the IDOR fix in
``duplicate_chat_session_for_user_from_slack``: the endpoint that backs
``POST /chat/seed-chat-session-from-slack`` used to read the source session
with ``user_id=None`` (ignoring permissions), so any authenticated user could
copy an arbitrary other user's chat session into a session they own and read it
back. The fix scopes the source lookup to the caller and requires the source to
be a Slack-originated session.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.chat import create_chat_session, duplicate_chat_session_for_user_from_slack
from onyx.db.models import Persona
from tests.external_dependency_unit.conftest import create_test_user


def test_cannot_seed_from_another_users_session(db_session: Session) -> None:
    """An attacker cannot copy a session owned by another user."""
    attacker = create_test_user(db_session, "attacker")
    victim = create_test_user(db_session, "victim")

    victim_session = create_chat_session(
        db_session=db_session,
        description="victim private chat",
        user_id=victim.id,
        persona_id=None,
        onyxbot_flow=False,
    )

    # The source lookup is now scoped to the caller, so the victim's session is
    # invisible and no copy is made.
    with pytest.raises(ValueError):
        duplicate_chat_session_for_user_from_slack(
            db_session=db_session,
            user=attacker,
            chat_session_id=victim_session.id,
        )


def test_cannot_seed_from_non_slack_unowned_session(db_session: Session) -> None:
    """Even an unowned (user_id is None) session can't be copied unless it is
    Slack-originated, so arbitrary bot/eval sessions aren't exfiltrated."""
    attacker = create_test_user(db_session, "attacker")

    unowned_web_session = create_chat_session(
        db_session=db_session,
        description="",
        user_id=None,
        persona_id=None,
        onyxbot_flow=False,
    )

    with pytest.raises(ValueError):
        duplicate_chat_session_for_user_from_slack(
            db_session=db_session,
            user=attacker,
            chat_session_id=unowned_web_session.id,
        )


def test_can_seed_from_slack_session(db_session: Session) -> None:
    """The legitimate flow still works: a Slack-originated (unowned) session is
    copied into a new session owned by the requesting user."""
    user = create_test_user(db_session, "slack-user")
    persona = Persona(
        name=f"seed-test-{uuid4().hex[:6]}",
        description="t",
        user_id=user.id,
    )
    db_session.add(persona)
    db_session.flush()

    slack_session = create_chat_session(
        db_session=db_session,
        description="",
        user_id=None,
        persona_id=persona.id,
        onyxbot_flow=True,
        slack_thread_id=f"T-{uuid4().hex[:8]}",
    )

    new_session = duplicate_chat_session_for_user_from_slack(
        db_session=db_session,
        user=user,
        chat_session_id=slack_session.id,
    )

    assert new_session.id != slack_session.id
    assert new_session.user_id == user.id
