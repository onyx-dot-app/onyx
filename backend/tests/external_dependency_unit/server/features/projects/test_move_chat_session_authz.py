"""Authorization test for ``move_chat_session`` project ownership.

``POST /user/projects/{project_id}/move_chat_session`` set
``chat_session.project_id`` from the path param without checking that the
project belonged to the caller, so a user could attach their own session to
another user's project and read that project's instructions back through the
default agent. The endpoint now verifies project ownership before assigning.
"""

import pytest
from sqlalchemy.orm import Session

from onyx.db.chat import create_chat_session
from onyx.db.models import UserProject
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.projects.api import move_chat_session
from onyx.server.features.projects.models import ChatSessionRequest
from tests.external_dependency_unit.conftest import create_test_user


def test_cannot_move_session_into_another_users_project(db_session: Session) -> None:
    attacker = create_test_user(db_session, "attacker")
    victim = create_test_user(db_session, "victim")

    attacker_session = create_chat_session(
        db_session=db_session,
        description="",
        user_id=attacker.id,
        persona_id=None,
    )
    victim_project = UserProject(name="victim-project", user_id=victim.id)
    db_session.add(victim_project)
    db_session.flush()

    with pytest.raises(OnyxError) as exc:
        move_chat_session(
            project_id=victim_project.id,
            body=ChatSessionRequest(chat_session_id=str(attacker_session.id)),
            user=attacker,
            db_session=db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND

    # The session must not have been attached to the victim's project.
    db_session.refresh(attacker_session)
    assert attacker_session.project_id is None


def test_can_move_session_into_own_project(db_session: Session) -> None:
    user = create_test_user(db_session, "owner")

    session = create_chat_session(
        db_session=db_session,
        description="",
        user_id=user.id,
        persona_id=None,
    )
    project = UserProject(name="own-project", user_id=user.id)
    db_session.add(project)
    db_session.flush()

    resp = move_chat_session(
        project_id=project.id,
        body=ChatSessionRequest(chat_session_id=str(session.id)),
        user=user,
        db_session=db_session,
    )
    assert resp.status_code == 204

    db_session.refresh(session)
    assert session.project_id == project.id
