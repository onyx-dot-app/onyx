from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill__User, Skill__UserGroup, UserSkillPreference
from onyx.db.skill import (
    SkillAccessPolicy,
    enable_new_skill_if_name_available__no_commit,
    list_skills,
    replace_skill_shares,
    set_skill_enabled_for_user,
    skill_user_states,
    transfer_skill_ownership,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.response_helpers import skill_response_for_user
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_group,
    make_skill,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)


def _direct_share_permissions(
    db_session: Session, skill_id: UUID
) -> dict[UUID, SkillSharePermission]:
    rows = db_session.scalars(
        select(Skill__User).where(Skill__User.skill_id == skill_id)
    ).all()
    return {row.user_id: row.permission for row in rows}


def _group_share_permissions(
    db_session: Session, skill_id: UUID
) -> dict[int, SkillSharePermission]:
    rows = db_session.scalars(
        select(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill_id)
    ).all()
    return {row.user_group_id: row.permission for row in rows}


def test_skill_user_states_resolve_defaults_and_visibility(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    visible_custom = make_skill(db_session, is_public=True)
    hidden_custom = make_skill(db_session, is_public=False)
    invalid_custom = make_skill(
        db_session,
        is_public=True,
        name=f"invalid-{uuid4().hex[:8]}",
    )
    invalid_custom.is_valid = False
    built_in = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"built-in-{uuid4().hex[:8]}",
    )

    states = skill_user_states(
        user,
        [visible_custom.id, hidden_custom.id, invalid_custom.id, built_in.id],
        db_session,
    )

    assert states[visible_custom.id].enabled is False
    assert states[visible_custom.id].can_toggle is True
    assert states[hidden_custom.id].can_toggle is False
    assert states[invalid_custom.id].can_toggle is False
    assert states[built_in.id].enabled is True
    assert states[built_in.id].can_toggle is False


def test_new_skill_is_enabled_only_when_name_is_available(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    name = f"auto-enable-{uuid4().hex[:8]}"
    first_skill = make_skill(db_session, name=name, is_public=True)
    second_skill = make_skill(db_session, name=name, is_public=True)

    assert enable_new_skill_if_name_available__no_commit(
        first_skill, user.id, db_session
    )
    assert not enable_new_skill_if_name_available__no_commit(
        second_skill, user.id, db_session
    )
    assert set(
        db_session.scalars(
            select(UserSkillPreference.skill_id).where(
                UserSkillPreference.user_id == user.id,
                UserSkillPreference.name == name,
            )
        )
    ) == {first_skill.id}


def test_orphaned_private_skill_has_boolean_admin_state(
    db_session: Session,
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN)
    orphaned_skill = make_skill(
        db_session,
        is_public=False,
        author_user_id=None,
    )

    state = skill_user_states(admin, [orphaned_skill.id], db_session)[orphaned_skill.id]

    assert state.can_toggle is False
    response = skill_response_for_user(
        orphaned_skill,
        admin,
        db_session,
        state=state,
        user_group_ids=set(),
    )
    assert response.can_toggle is False


def test_replace_skill_shares_replaces_requested_share_types(
    db_session: Session,
) -> None:
    old_user = make_user(db_session)
    new_user = make_user(db_session)
    old_group = make_group(db_session)
    new_group = make_group(db_session)
    skill = make_skill(db_session)
    share_skill_with_user(
        db_session,
        skill,
        old_user,
        SkillSharePermission.EDITOR,
    )
    share_skill_with_group(
        db_session,
        skill,
        old_group,
        SkillSharePermission.EDITOR,
    )

    replace_skill_shares(
        skill=skill,
        user_shares={new_user.id: SkillSharePermission.VIEWER},
        group_shares={new_group.id: SkillSharePermission.EDITOR},
        db_session=db_session,
    )

    assert _direct_share_permissions(db_session, skill.id) == {
        new_user.id: SkillSharePermission.VIEWER
    }
    assert _group_share_permissions(db_session, skill.id) == {
        new_group.id: SkillSharePermission.EDITOR
    }


def test_replace_skill_shares_leaves_omitted_share_types_unchanged(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    group = make_group(db_session)
    skill = make_skill(db_session)
    share_skill_with_user(db_session, skill, user, SkillSharePermission.VIEWER)
    share_skill_with_group(db_session, skill, group, SkillSharePermission.EDITOR)

    replace_skill_shares(
        skill=skill,
        user_shares={},
        db_session=db_session,
    )

    assert _direct_share_permissions(db_session, skill.id) == {}
    assert _group_share_permissions(db_session, skill.id) == {
        group.id: SkillSharePermission.EDITOR
    }


def test_replace_skill_shares_names_invalid_group_target(
    db_session: Session,
) -> None:
    skill = make_skill(db_session)

    with pytest.raises(OnyxError) as exc_info:
        replace_skill_shares(
            skill=skill,
            group_shares={-1: SkillSharePermission.VIEWER},
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == "One or more group share targets do not exist."


def test_replace_skill_shares_names_invalid_user_target(
    db_session: Session,
) -> None:
    skill = make_skill(db_session)

    with pytest.raises(OnyxError) as exc_info:
        replace_skill_shares(
            skill=skill,
            user_shares={uuid4(): SkillSharePermission.VIEWER},
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == "One or more user share targets do not exist."


def test_transfer_skill_ownership_removes_new_owner_direct_share_and_upgrades_previous_owner(
    db_session: Session,
) -> None:
    previous_owner = make_user(db_session)
    new_owner = make_user(db_session)
    skill = make_skill(db_session, author_user_id=previous_owner.id)
    share_skill_with_user(
        db_session,
        skill,
        previous_owner,
        SkillSharePermission.VIEWER,
    )
    share_skill_with_user(
        db_session,
        skill,
        new_owner,
        SkillSharePermission.EDITOR,
    )

    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=new_owner.id,
        db_session=db_session,
    )

    assert skill.author_user_id == new_owner.id
    direct_shares = _direct_share_permissions(db_session, skill.id)
    assert direct_shares == {previous_owner.id: SkillSharePermission.EDITOR}


def test_transfer_skill_ownership_does_not_enable_skill_for_new_owner(
    db_session: Session,
) -> None:
    previous_owner = make_user(db_session)
    new_owner = make_user(db_session)
    skill = make_skill(db_session, author_user_id=previous_owner.id)

    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=new_owner.id,
        db_session=db_session,
    )

    assert skill.author_user_id == new_owner.id
    direct_shares = _direct_share_permissions(db_session, skill.id)
    assert direct_shares == {previous_owner.id: SkillSharePermission.EDITOR}
    preference = db_session.get(
        UserSkillPreference,
        {"user_id": new_owner.id, "skill_id": skill.id},
    )
    assert preference is None


def test_transfer_skill_ownership_preserves_new_owner_selection(
    db_session: Session,
) -> None:
    previous_owner = make_user(db_session)
    new_owner = make_user(db_session)
    skill = make_skill(
        db_session,
        is_public=True,
        author_user_id=previous_owner.id,
    )
    preference = UserSkillPreference(
        user_id=new_owner.id,
        skill_id=skill.id,
        name=skill.name,
    )
    db_session.add(preference)
    db_session.flush()

    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=new_owner.id,
        db_session=db_session,
    )

    assert skill.author_user_id == new_owner.id
    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": new_owner.id, "skill_id": skill.id},
        )
        is preference
    )


def test_same_name_skills_switch_atomically_per_user(db_session: Session) -> None:
    first_user = make_user(db_session)
    second_user = make_user(db_session)
    name = f"shared-name-{uuid4().hex[:8]}"
    first_skill = make_skill(db_session, name=name, is_public=True)
    second_skill = make_skill(db_session, name=name, is_public=True)

    set_skill_enabled_for_user(
        skill_id=first_skill.id,
        enabled=True,
        user=first_user,
        db_session=db_session,
    )
    set_skill_enabled_for_user(
        skill_id=first_skill.id,
        enabled=True,
        user=first_user,
        db_session=db_session,
    )
    set_skill_enabled_for_user(
        skill_id=second_skill.id,
        enabled=True,
        user=second_user,
        db_session=db_session,
    )

    assert {
        skill.id
        for skill in list_skills(
            policy=SkillAccessPolicy.USE,
            user=first_user,
            db_session=db_session,
        )
        if skill.name == name
    } == {first_skill.id}
    assert {
        skill.id
        for skill in list_skills(
            policy=SkillAccessPolicy.USE,
            user=second_user,
            db_session=db_session,
        )
        if skill.name == name
    } == {second_skill.id}

    with pytest.raises(OnyxError) as exc_info:
        set_skill_enabled_for_user(
            skill_id=second_skill.id,
            enabled=True,
            user=first_user,
            db_session=db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT
    assert (
        db_session.scalar(
            select(UserSkillPreference.skill_id).where(
                UserSkillPreference.user_id == first_user.id,
                UserSkillPreference.name == name,
            )
        )
        == first_skill.id
    )

    set_skill_enabled_for_user(
        skill_id=second_skill.id,
        enabled=True,
        replace_conflict=True,
        user=first_user,
        db_session=db_session,
    )

    preferences = list(
        db_session.scalars(
            select(UserSkillPreference)
            .where(UserSkillPreference.user_id == first_user.id)
            .where(UserSkillPreference.name == name)
        )
    )
    assert {preference.skill_id for preference in preferences} == {second_skill.id}


def test_disabling_skill_deletes_selection(db_session: Session) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=True,
        user=user,
        db_session=db_session,
    )

    set_skill_enabled_for_user(
        skill_id=skill.id,
        enabled=False,
        user=user,
        db_session=db_session,
    )

    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": user.id, "skill_id": skill.id},
        )
        is None
    )


def test_database_rejects_two_same_name_preferences(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    name = f"constrained-name-{uuid4().hex[:8]}"
    first_skill = make_skill(db_session, name=name, is_public=True)
    second_skill = make_skill(db_session, name=name, is_public=True)
    db_session.add(
        UserSkillPreference(
            user_id=user.id,
            skill_id=first_skill.id,
            name=name,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                UserSkillPreference(
                    user_id=user.id,
                    skill_id=second_skill.id,
                    name=name,
                )
            )
            db_session.flush()


def test_preference_name_must_match_skill_name(db_session: Session) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                UserSkillPreference(
                    user_id=user.id,
                    skill_id=skill.id,
                    name="different-name",
                )
            )
            db_session.flush()


def test_transfer_skill_ownership_self_transfer_preserves_direct_share(
    db_session: Session,
) -> None:
    owner = make_user(db_session)
    skill = make_skill(db_session, author_user_id=owner.id)
    share_skill_with_user(
        db_session,
        skill,
        owner,
        SkillSharePermission.VIEWER,
    )

    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=owner.id,
        db_session=db_session,
    )

    assert skill.author_user_id == owner.id
    direct_shares = _direct_share_permissions(db_session, skill.id)
    assert direct_shares == {owner.id: SkillSharePermission.VIEWER}


def test_transfer_skill_ownership_rejects_built_in_skill(
    db_session: Session,
) -> None:
    new_owner = make_user(db_session)
    skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"built-in-{new_owner.id.hex[:8]}",
    )

    with pytest.raises(OnyxError) as exc_info:
        transfer_skill_ownership(
            skill=skill,
            new_owner_user_id=new_owner.id,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert skill.author_user_id is None


def test_transfer_skill_ownership_rejects_missing_new_owner(
    db_session: Session,
) -> None:
    previous_owner = make_user(db_session)
    skill = make_skill(db_session, author_user_id=previous_owner.id)

    with pytest.raises(OnyxError) as exc_info:
        transfer_skill_ownership(
            skill=skill,
            new_owner_user_id=uuid4(),
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == "New owner user does not exist."
