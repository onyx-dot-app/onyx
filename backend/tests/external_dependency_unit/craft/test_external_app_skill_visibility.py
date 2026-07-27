"""External-app skill management and runtime dependency behavior."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.external_app import (
    get_external_app_by_skill_id,
    get_skills_for_external_app,
)
from onyx.db.models import ExternalApp__Skill, User, UserRole, UserSkillPreference
from onyx.db.skill import (
    SkillManagementPolicy,
    fetch_skill,
    list_runtime_skills_for_user,
    list_skills,
    set_skill_enabled_for_user,
    set_skill_public_permission,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_external_app,
    make_skill,
    make_user,
    make_user_credential,
)

_AUTH_TEMPLATE = {"token": "{token}", "account": "{account}"}
_FULL_CREDS = {"token": "t", "account": "a"}


def _management_skill_ids(
    user: User,
    db_session: Session,
    policy: SkillManagementPolicy,
) -> set[UUID]:
    return {
        skill.id
        for skill in list_skills(
            policy=policy,
            user=user,
            db_session=db_session,
        )
    }


def _runtime_skill_ids(user: User, db_session: Session) -> set[UUID]:
    return {
        skill.id
        for skill in list_runtime_skills_for_user(
            user=user,
            db_session=db_session,
        )
    }


def test_view_exposes_associated_custom_skill_regardless_of_authentication(
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
        assert skill.id in _management_skill_ids(
            user, db_session, SkillManagementPolicy.VIEW
        )
        assert (
            fetch_skill(
                skill.id,
                policy=SkillManagementPolicy.VIEW,
                user=user,
                db_session=db_session,
            )
            == skill
        )


def test_admin_view_includes_associated_custom_but_hides_associated_builtin(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN)
    regular = make_skill(db_session, is_public=True, name="plain-admin-skill")
    custom = make_skill(db_session, is_public=True, name="ext-admin-custom")
    built_in = make_built_in_skill_row(
        db_session,
        built_in_skill_id="ext-admin-builtin",
    )
    make_external_app(db_session, skill=custom, auth_template={})
    make_external_app(db_session, skill=built_in, auth_template={})

    visible = _management_skill_ids(admin, db_session, SkillManagementPolicy.VIEW)
    assert regular.id in visible
    assert custom.id in visible
    assert built_in.id not in visible
    assert custom.id in _management_skill_ids(
        admin, db_session, SkillManagementPolicy.EDIT
    )
    assert built_in.id not in _management_skill_ids(
        admin, db_session, SkillManagementPolicy.EDIT
    )


def test_associated_custom_skill_requires_normal_user_selection(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template={})

    assert skill.id not in _runtime_skill_ids(user, db_session)

    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=True,
        user=user,
        db_session=db_session,
    )
    assert skill.id in _runtime_skill_ids(user, db_session)


def test_runtime_requires_selection_and_authenticated_external_app(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)

    assert skill.id not in _runtime_skill_ids(user, db_session)
    with pytest.raises(OnyxError) as exc_info:
        set_skill_enabled_for_user(
            skill_id=skill.id,
            enabled=True,
            user=user,
            db_session=db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT

    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id not in _runtime_skill_ids(user, db_session)
    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=True,
        user=user,
        db_session=db_session,
    )
    assert skill.id in _runtime_skill_ids(user, db_session)


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
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)
    for skill in (first_skill, second_skill):
        set_skill_enabled_for_user(
            skill_id=skill.id,
            enabled=True,
            user=user,
            db_session=db_session,
        )

    assert get_skills_for_external_app(db_session, app.id) == [
        first_skill,
        second_skill,
    ]
    assert get_external_app_by_skill_id(db_session, second_skill.id) == app
    usable = _runtime_skill_ids(user, db_session)
    assert {first_skill.id, second_skill.id} <= usable

    app.enabled = False
    db_session.flush()
    assert not {
        first_skill.id,
        second_skill.id,
    } & _runtime_skill_ids(user, db_session)


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


def test_runtime_excludes_disabled_external_app(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(
        db_session,
        skill=skill,
        auth_template=_AUTH_TEMPLATE,
    )
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)
    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=True,
        user=user,
        db_session=db_session,
    )

    app.enabled = False
    db_session.flush()
    assert skill.id not in _runtime_skill_ids(user, db_session)

    app.enabled = True
    db_session.flush()

    assert skill.id in _runtime_skill_ids(user, db_session)


def test_runtime_excludes_unauthenticated_or_partially_authenticated_external_app(
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
    for user in (unauthenticated_user, partial_user):
        db_session.add(
            UserSkillPreference(
                user_id=user.id,
                skill_id=skill.id,
                name=skill.name,
            )
        )
    db_session.flush()

    assert skill.id not in _runtime_skill_ids(unauthenticated_user, db_session)
    assert skill.id not in _runtime_skill_ids(partial_user, db_session)


def test_runtime_includes_external_app_with_no_user_credentials_required(
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
    for skill in (empty_template_skill, org_filled_skill):
        set_skill_enabled_for_user(
            skill_id=skill.id,
            enabled=True,
            user=user,
            db_session=db_session,
        )

    usable = _runtime_skill_ids(user, db_session)
    assert empty_template_skill.id in usable
    assert org_filled_skill.id in usable


def test_associated_same_name_switch_changes_only_the_acting_user(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    first_user = make_user(db_session)
    second_user = make_user(db_session)
    standalone = make_skill(db_session, is_public=True, name="shared-runtime-name")
    associated = make_skill(db_session, is_public=True, name="shared-runtime-name")
    make_external_app(db_session, skill=associated, auth_template={})

    for user in (first_user, second_user):
        set_skill_enabled_for_user(
            skill_id=standalone.id,
            enabled=True,
            user=user,
            db_session=db_session,
        )

    with pytest.raises(OnyxError) as exc_info:
        set_skill_enabled_for_user(
            skill_id=associated.id,
            enabled=True,
            user=first_user,
            db_session=db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT

    set_skill_enabled_for_user(
        skill_id=associated.id,
        enabled=True,
        replace_conflict=True,
        user=first_user,
        db_session=db_session,
    )

    assert associated.id in _runtime_skill_ids(first_user, db_session)
    assert standalone.id not in _runtime_skill_ids(first_user, db_session)
    assert standalone.id in _runtime_skill_ids(second_user, db_session)
    assert associated.id not in _runtime_skill_ids(second_user, db_session)


def test_associated_builtin_stays_hidden_and_uses_app_readiness_without_preference(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id="external-provider-system-skill",
    )
    app = make_external_app(
        db_session,
        skill=skill,
        auth_template=_AUTH_TEMPLATE,
    )

    assert skill.id not in _management_skill_ids(
        user, db_session, SkillManagementPolicy.VIEW
    )
    assert skill.id not in _management_skill_ids(
        user, db_session, SkillManagementPolicy.EDIT
    )
    assert skill.id not in _runtime_skill_ids(user, db_session)

    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id in _runtime_skill_ids(user, db_session)


@pytest.mark.parametrize(
    "public_permission",
    [None, SkillSharePermission.EDITOR],
)
def test_associated_skill_cannot_change_required_org_viewer_visibility(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    public_permission: SkillSharePermission | None,
) -> None:
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template={})

    with pytest.raises(OnyxError) as exc_info:
        set_skill_public_permission(
            skill=skill,
            public_permission=public_permission,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert skill.public_permission == SkillSharePermission.VIEWER


def test_regular_shared_skill_still_requires_enabled_preference(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True, name="plain-skill")

    assert skill.id in _management_skill_ids(
        user, db_session, SkillManagementPolicy.VIEW
    )
    assert skill.id not in _runtime_skill_ids(user, db_session)

    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=True,
        user=user,
        db_session=db_session,
    )

    assert skill.id in _runtime_skill_ids(user, db_session)
