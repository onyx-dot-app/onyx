"""A bulk share applies one access change to every skill and pushes once."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db import plugin as plugin_db
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Sandbox, User
from onyx.server.features.skill.api import bulk_update_skills
from onyx.server.features.skill.models import (
    SkillBulkShareRequest,
    SkillBulkSharing,
    SkillUserShareRequest,
)
from tests.external_dependency_unit.craft.db_helpers import (
    make_sandbox,
    make_skill,
    make_user,
    share_skill_with_user,
)

_SKILL_COUNT = 100


def test_bulk_share_of_many_skills_pushes_once(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user(db_session, standard_account=True)
    previous_viewer = make_user(db_session, standard_account=True)
    new_viewer = make_user(db_session, standard_account=True)
    sandbox_ids = [
        make_sandbox(db_session, user).id
        for user in (owner, previous_viewer, new_viewer)
    ]
    skills = [
        make_skill(db_session, author_user_id=owner.id) for _ in range(_SKILL_COUNT)
    ]
    share_skill_with_user(db_session, skills[0], previous_viewer)
    db_session.commit()

    try:
        push = MagicMock()
        monkeypatch.setattr("onyx.skills.push.push_skills_for_users", push)
        affected_reads = MagicMock(wraps=plugin_db.affected_user_ids_for_plugins)
        with patch.object(plugin_db, "affected_user_ids_for_plugins", affected_reads):
            response = bulk_update_skills(
                SkillBulkShareRequest(
                    skill_ids=[skill.id for skill in skills],
                    action="share",
                    sharing=SkillBulkSharing(
                        user_shares=[
                            SkillUserShareRequest(
                                user_id=new_viewer.id,
                                permission=SkillSharePermission.VIEWER,
                            )
                        ]
                    ),
                ),
                user=owner,
                db_session=db_session,
            )

        assert response.failed == []
        assert len(response.succeeded) == _SKILL_COUNT
        # One read of the affected users for the whole set before the change,
        # and one after.
        assert affected_reads.call_count == 2
        push.assert_called_once()
        pushed: set[UUID] = push.call_args.args[0]
        assert {owner.id, previous_viewer.id, new_viewer.id} <= pushed
    finally:
        db_session.rollback()
        db_session.execute(delete(Sandbox).where(Sandbox.id.in_(sandbox_ids)))
        db_session.commit()
