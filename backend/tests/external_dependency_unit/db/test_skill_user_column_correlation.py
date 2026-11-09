"""Per-user predicates must correlate the outer user, including aliases."""

import pytest
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from onyx.db import skill as skill_db
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill, Skill__UserGroup, User, UserSkillPreference
from onyx.db.skill import resolve_skill_runtime_names
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_skill,
    make_user,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest.mark.parametrize("alias", [False, True])
def test_outer_user_preferences(session: Session, alias: bool) -> None:
    first, second = (make_user(session, standard_account=True) for _ in range(2))
    skill = make_skill(session, is_public=True, is_valid=True)
    session.add_all(
        [
            UserSkillPreference(
                user_id=u.id, skill_id=skill.id, name=skill.name, enabled=e
            )
            for u, e in ((first, True), (second, False))
        ]
    )
    session.flush()
    outer = (
        select(User.__table__.c.id)
        .where(User.__table__.c.id.in_([first.id, second.id]))
        .subquery()
        if alias
        else User.__table__
    )
    rows = dict(
        session.execute(
            select(outer.c.id, skill_db._is_enabled_for_user(outer.c.id))
            .select_from(outer)
            .join(Skill, true())
            .where(Skill.id == skill.id, outer.c.id.in_([first.id, second.id]))
        )
        .tuples()
        .all()
    )
    assert rows == {first.id: True, second.id: False}
    assert skill.id in resolve_skill_runtime_names(first, session).values()
    assert skill.id not in resolve_skill_runtime_names(second, session).values()


def test_outer_user_group_visibility(session: Session) -> None:
    first, second = (make_user(session, standard_account=True) for _ in range(2))
    skill = make_skill(session, is_public=True, is_valid=True)
    skill.installation_policy = Policy.NOT_AVAILABLE
    group = make_group(session)
    add_user_to_group(session, first, group)
    session.add(
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group.id,
            permission=SkillSharePermission.VIEWER,
            installation_policy=Policy.REQUIRED,
        )
    )
    session.flush()
    outer = (
        select(User.__table__.c.id)
        .where(User.__table__.c.id.in_([first.id, second.id]))
        .subquery()
    )
    rows = dict(
        session.execute(
            select(outer.c.id, skill_db.skill_visible_to_user(outer.c.id))
            .select_from(outer)
            .join(Skill, true())
            .where(Skill.id == skill.id)
        )
        .tuples()
        .all()
    )
    assert rows == {first.id: True, second.id: False}
