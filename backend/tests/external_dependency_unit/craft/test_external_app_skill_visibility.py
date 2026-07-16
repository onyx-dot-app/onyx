"""Visibility, enablement, and credential gates for external-app skills."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.skill import list_skills
from onyx.db.skill import set_skill_enabled_for_user
from onyx.db.skill import skill_user_states
from onyx.db.skill import SkillAccessPolicy
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import make_user_credential

_AUTH_TEMPLATE = {"token": "{token}", "account": "{account}"}
_FULL_CREDS = {"token": "t", "account": "a"}


def _skill_ids(
    user: User,
    db_session: Session,
    policy: SkillAccessPolicy,
) -> set[UUID]:
    return {
        skill.id
        for skill in list_skills(
            policy=policy,
            user=user,
            db_session=db_session,
        )
    }


def _enable(skill_id: UUID, user: User, db_session: Session) -> None:
    set_skill_enabled_for_user(
        skill_id=skill_id,
        enabled=True,
        user=user,
        db_session=db_session,
    )


def test_view_lists_visible_external_app_before_authentication(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.VIEW)
    state = skill_user_states(user, [skill.id], db_session)[skill.id]
    assert state.enabled is False
    assert state.can_toggle is True
    assert state.is_external_app is True


def test_admin_view_lists_external_apps(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template={})

    assert skill.id in _skill_ids(admin, db_session, SkillAccessPolicy.VIEW)


def test_authenticated_external_app_requires_enabled_preference(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id not in _skill_ids(user, db_session, SkillAccessPolicy.USE)

    _enable(skill.id, user, db_session)

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.USE)


def test_enabled_external_app_still_requires_complete_credentials(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(
        db_session,
        app=app,
        user=user,
        user_credentials={"token": "t"},
    )
    _enable(skill.id, user, db_session)

    assert skill.id not in _skill_ids(user, db_session, SkillAccessPolicy.USE)


def test_enabled_external_app_without_user_credentials_is_usable(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    empty_template_skill = make_skill(
        db_session,
        is_public=True,
        slug="ext-empty-template",
    )
    make_external_app(
        db_session,
        skill=empty_template_skill,
        auth_template={},
    )
    org_filled_skill = make_skill(
        db_session,
        is_public=True,
        slug="ext-org-fills-all",
    )
    make_external_app(
        db_session,
        skill=org_filled_skill,
        auth_template={"token": "static"},
        organization_credentials={"token": "from-org"},
    )
    _enable(empty_template_skill.id, user, db_session)
    _enable(org_filled_skill.id, user, db_session)

    usable = _skill_ids(user, db_session, SkillAccessPolicy.USE)
    assert empty_template_skill.id in usable
    assert org_filled_skill.id in usable


def test_regular_shared_skill_also_requires_enabled_preference(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True, slug="plain-skill")

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.VIEW)
    assert skill.id not in _skill_ids(user, db_session, SkillAccessPolicy.USE)

    _enable(skill.id, user, db_session)

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.USE)
