"""External-app skills are hidden from skill management and gated by auth."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.external_app import (
    get_external_app_by_skill_id,
    get_first_skill_for_external_app,
)
from onyx.db.models import ExternalApp__Skill, User, UserRole
from onyx.db.skill import (
    SkillAccessPolicy,
    fetch_skill,
    list_skills,
    set_skill_enabled_for_user,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
    make_user,
    make_user_credential,
)

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


def test_view_hides_external_app_regardless_of_authentication(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    unauthenticated_user = make_user(db_session)
    authenticated_user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(
        db_session,
        app=app,
        user=authenticated_user,
        user_credentials=_FULL_CREDS,
    )

    for user in (unauthenticated_user, authenticated_user):
        assert skill.id not in _skill_ids(user, db_session, SkillAccessPolicy.VIEW)
        assert (
            fetch_skill(
                skill.id,
                policy=SkillAccessPolicy.VIEW,
                user=user,
                db_session=db_session,
            )
            is None
        )


def test_admin_view_hides_external_apps(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN)
    regular = make_skill(db_session, is_public=True, name="plain-admin-skill")
    external = make_skill(db_session, is_public=True, name="ext-admin-hidden")
    make_external_app(db_session, skill=external, auth_template={})

    visible = _skill_ids(admin, db_session, SkillAccessPolicy.VIEW)
    assert regular.id in visible
    assert external.id not in visible


def test_external_app_preference_cannot_be_set(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template={})

    with pytest.raises(OnyxError) as exc_info:
        set_skill_enabled_for_user(
            skill_id=skill.id,
            enabled=False,
            user=user,
            db_session=db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND


def test_use_includes_authenticated_external_app_without_preference(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.USE)


def test_one_external_app_can_gate_multiple_skills(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    first_skill = make_skill(db_session, is_public=True, name="first-app-skill")
    second_skill = make_skill(db_session, is_public=True, name="second-app-skill")
    app = make_external_app(
        db_session,
        skill=first_skill,
        auth_template=_AUTH_TEMPLATE,
    )
    db_session.add(ExternalApp__Skill(external_app_id=app.id, skill_id=second_skill.id))
    db_session.flush()

    assert get_first_skill_for_external_app(db_session, app.id) == first_skill
    assert not {
        first_skill.id,
        second_skill.id,
    } & _skill_ids(user, db_session, SkillAccessPolicy.USE)

    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)
    db_session.flush()

    assert get_external_app_by_skill_id(db_session, second_skill.id) == app
    usable = _skill_ids(user, db_session, SkillAccessPolicy.USE)
    assert {first_skill.id, second_skill.id} <= usable

    app.enabled = False
    db_session.flush()
    assert not {
        first_skill.id,
        second_skill.id,
    } & _skill_ids(user, db_session, SkillAccessPolicy.USE)


def test_one_skill_cannot_be_associated_with_two_external_apps(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    shared_skill = make_skill(db_session, name="single-app-dependency")
    first_app = make_external_app(
        db_session,
        skill=shared_skill,
        auth_template={},
    )
    second_app = make_external_app(
        db_session,
        skill=make_skill(db_session, name="second-app-own-skill"),
        auth_template={},
    )

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                ExternalApp__Skill(
                    external_app_id=second_app.id,
                    skill_id=shared_skill.id,
                )
            )
            db_session.flush()

    assert get_external_app_by_skill_id(db_session, shared_skill.id) == first_app


def test_use_excludes_disabled_external_app(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(
        db_session,
        skill=skill,
        auth_template=_AUTH_TEMPLATE,
        enabled=False,
    )
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id not in _skill_ids(user, db_session, SkillAccessPolicy.USE)

    app.enabled = True
    db_session.flush()

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.USE)


def test_use_excludes_unauthenticated_or_partially_authenticated_external_app(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    unauthenticated_user = make_user(db_session)
    partial_user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(
        db_session,
        app=app,
        user=partial_user,
        user_credentials={"token": "t"},
    )

    assert skill.id not in _skill_ids(
        unauthenticated_user, db_session, SkillAccessPolicy.USE
    )
    assert skill.id not in _skill_ids(partial_user, db_session, SkillAccessPolicy.USE)


def test_use_includes_external_app_with_no_user_credentials_required(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    empty_template_skill = make_skill(
        db_session,
        is_public=True,
        name="ext-empty-template",
    )
    make_external_app(db_session, skill=empty_template_skill, auth_template={})
    org_filled_skill = make_skill(
        db_session,
        is_public=True,
        name="ext-org-fills-all",
    )
    make_external_app(
        db_session,
        skill=org_filled_skill,
        auth_template={"token": "static"},
        organization_credentials={"token": "from-org"},
    )

    usable = _skill_ids(user, db_session, SkillAccessPolicy.USE)
    assert empty_template_skill.id in usable
    assert org_filled_skill.id in usable


def test_regular_shared_skill_still_requires_enabled_preference(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True, name="plain-skill")

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.VIEW)
    assert skill.id not in _skill_ids(user, db_session, SkillAccessPolicy.USE)

    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=True,
        user=user,
        db_session=db_session,
    )

    assert skill.id in _skill_ids(user, db_session, SkillAccessPolicy.USE)
