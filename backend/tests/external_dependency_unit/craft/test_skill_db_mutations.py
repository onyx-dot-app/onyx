from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import (
    Skill,
    Skill__User,
    Skill__UserGroup,
    UserSkillPreference,
)
from onyx.db.skill import (
    add_new_skill__no_commit,
    enable_new_skill_if_name_available__no_commit,
    list_runtime_skills_for_user,
    replace_skill_bundle,
    replace_skill_shares,
    set_skill_enabled_for_user,
    set_skill_installation_policy,
    set_skill_public_permission,
    skill_user_states,
    transfer_skill_ownership,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_external_app,
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


def test_new_skill_name_is_not_reserved_by_external_app_association(
    db_session: Session,
) -> None:
    name = f"shared-skill-name-{uuid4().hex[:8]}"
    associated_skill = make_skill(db_session, name=name, is_public=True)
    make_external_app(db_session, skill=associated_skill, auth_template={})
    standalone_skill = Skill(
        id=uuid4(),
        name=name,
        description="Independent skill with the same runtime name",
        author_user_id=make_user(db_session, standard_account=True).id,
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
        is_valid=True,
    )

    add_new_skill__no_commit(standalone_skill, db_session)

    assert set(db_session.scalars(select(Skill.id).where(Skill.name == name))) == {
        associated_skill.id,
        standalone_skill.id,
    }


def test_private_skill_requires_an_owner(db_session: Session) -> None:
    skill = make_skill(db_session)
    with pytest.raises(IntegrityError, match="ck_private_skill_has_owner"):
        with db_session.begin_nested():
            skill.author_user_id = None
            db_session.flush()


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

    assert [share.user_id for share in skill.user_shares] == [old_user.id]
    assert [share.user_group_id for share in skill.group_shares] == [old_group.id]

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

    assert [share.user_id for share in skill.user_shares] == [new_user.id]
    assert [share.user_group_id for share in skill.group_shares] == [new_group.id]


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
        for skill in list_runtime_skills_for_user(
            user=first_user,
            db_session=db_session,
        )
        if skill.name == name
    } == {first_skill.id}
    assert {
        skill.id
        for skill in list_runtime_skills_for_user(
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
    assert {
        preference.skill_id for preference in preferences if preference.enabled
    } == {second_skill.id}


def test_disabling_skill_records_opt_out(db_session: Session) -> None:
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

    preference = db_session.get(
        UserSkillPreference, {"user_id": user.id, "skill_id": skill.id}
    )
    assert preference is not None
    assert preference.enabled is False


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


def test_installation_policies_preserve_choices_through_updates(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    assert not skill_user_states(user, [skill.id], db_session)[skill.id].enabled
    set_skill_installation_policy(skill, SkillInstallationPolicy.DEFAULT, db_session)
    assert skill_user_states(user, [skill.id], db_session)[skill.id].enabled
    # New users inherit the policy without preference rows.
    newcomer = make_user(db_session)
    assert skill_user_states(newcomer, [skill.id], db_session)[skill.id].enabled
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=False, user=user, db_session=db_session
    )
    replace_skill_bundle(
        skill=skill,
        new_bundle_file_id="updated-bundle",
        new_bundle_sha256="new-hash",
        new_description="Updated",
        db_session=db_session,
    )
    assert not skill_user_states(user, [skill.id], db_session)[skill.id].enabled
    assert skill_user_states(newcomer, [skill.id], db_session)[skill.id].enabled
    set_skill_installation_policy(skill, SkillInstallationPolicy.REQUIRED, db_session)
    state = skill_user_states(user, [skill.id], db_session)[skill.id]
    assert state.enabled and not state.can_toggle
    assert skill.id in {
        row.id for row in list_runtime_skills_for_user(user=user, db_session=db_session)
    }
    with pytest.raises(OnyxError):
        set_skill_enabled_for_user(
            skill_id=skill.id, enabled=False, user=user, db_session=db_session
        )
    set_skill_installation_policy(skill, SkillInstallationPolicy.DEFAULT, db_session)
    assert not skill_user_states(user, [skill.id], db_session)[skill.id].enabled
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=user, db_session=db_session
    )
    set_skill_installation_policy(skill, SkillInstallationPolicy.AVAILABLE, db_session)
    assert skill_user_states(user, [skill.id], db_session)[skill.id].enabled


def test_automatic_skill_name_conflicts(db_session: Session) -> None:
    user = make_user(db_session)
    name = f"policy-conflict-{uuid4().hex[:8]}"
    optional = make_skill(db_session, name=name, is_public=True)
    automatic = make_skill(db_session, name=name, is_public=True)
    set_skill_enabled_for_user(
        skill_id=optional.id, enabled=True, user=user, db_session=db_session
    )
    set_skill_installation_policy(
        automatic, SkillInstallationPolicy.DEFAULT, db_session
    )
    states = skill_user_states(user, [optional.id, automatic.id], db_session)
    assert states[optional.id].enabled and not states[automatic.id].enabled
    set_skill_installation_policy(
        automatic, SkillInstallationPolicy.REQUIRED, db_session
    )
    states = skill_user_states(user, [optional.id, automatic.id], db_session)
    assert not states[optional.id].enabled and states[automatic.id].enabled
    with pytest.raises(OnyxError) as error:
        set_skill_enabled_for_user(
            skill_id=optional.id,
            enabled=True,
            replace_conflict=True,
            user=user,
            db_session=db_session,
        )
    assert error.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT
    with pytest.raises(OnyxError) as error:
        set_skill_installation_policy(
            optional, SkillInstallationPolicy.DEFAULT, db_session
        )
    assert error.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT
    assert optional.installation_policy == SkillInstallationPolicy.AVAILABLE
    set_skill_installation_policy(
        automatic, SkillInstallationPolicy.AVAILABLE, db_session
    )
    assert skill_user_states(user, [optional.id], db_session)[optional.id].enabled


@pytest.mark.parametrize(
    "policy", [SkillInstallationPolicy.DEFAULT, SkillInstallationPolicy.REQUIRED]
)
def test_installation_policy_follows_invited_users_and_groups(
    db_session: Session, policy: SkillInstallationPolicy
) -> None:
    owner = make_user(db_session)
    invited = make_user(db_session)
    member = make_user(db_session)
    outsider = make_user(db_session)
    group = make_group(db_session)
    skill = make_skill(db_session, is_public=False, author_user_id=owner.id)
    share_skill_with_user(db_session, skill, invited)
    share_skill_with_group(db_session, skill, group)
    add_user_to_group(db_session, member, group)
    set_skill_installation_policy(skill, policy, db_session)
    for user in (owner, invited, member):
        state = skill_user_states(user, [skill.id], db_session)[skill.id]
        assert state.enabled
        assert state.can_toggle == (policy != SkillInstallationPolicy.REQUIRED)
        assert skill.id in {
            row.id
            for row in list_runtime_skills_for_user(user=user, db_session=db_session)
        }
    assert not skill_user_states(outsider, [skill.id], db_session)[skill.id].enabled
    # An inaccessible required skill cannot suppress an outsider's same-name skill.
    personal = make_skill(db_session, name=skill.name, author_user_id=outsider.id)
    set_skill_enabled_for_user(
        skill_id=personal.id, enabled=True, user=outsider, db_session=db_session
    )
    assert skill_user_states(outsider, [personal.id], db_session)[personal.id].enabled
    replace_skill_shares(
        skill=skill, user_shares={}, group_shares={}, db_session=db_session
    )
    for user in (invited, member):
        assert not skill_user_states(user, [skill.id], db_session)[skill.id].enabled
        assert skill.id not in {
            row.id
            for row in list_runtime_skills_for_user(user=user, db_session=db_session)
        }


def test_replacing_default_skill_remembers_opt_out(db_session: Session) -> None:
    user = make_user(db_session)
    name = f"default-replace-{uuid4().hex[:8]}"
    default = make_skill(db_session, name=name, is_public=True)
    other = make_skill(db_session, name=name, is_public=True)
    set_skill_installation_policy(default, SkillInstallationPolicy.DEFAULT, db_session)
    with pytest.raises(OnyxError):
        set_skill_enabled_for_user(
            skill_id=other.id, enabled=True, user=user, db_session=db_session
        )
    set_skill_enabled_for_user(
        skill_id=other.id,
        enabled=True,
        replace_conflict=True,
        user=user,
        db_session=db_session,
    )
    set_skill_enabled_for_user(
        skill_id=other.id, enabled=False, user=user, db_session=db_session
    )
    states = skill_user_states(user, [default.id, other.id], db_session)
    assert not states[default.id].enabled
    assert not states[other.id].enabled


@pytest.mark.parametrize("share_via_group", [False, True])
def test_inaccessible_selection_does_not_suppress_default(
    db_session: Session, share_via_group: bool
) -> None:
    owner = make_user(db_session)
    user = make_user(db_session)
    selected = make_skill(db_session, is_public=False, author_user_id=owner.id)
    group = make_group(db_session)
    if share_via_group:
        add_user_to_group(db_session, user, group)
        share_skill_with_group(db_session, selected, group)
    else:
        share_skill_with_user(db_session, selected, user)
    set_skill_enabled_for_user(
        skill_id=selected.id, enabled=True, user=user, db_session=db_session
    )
    default = make_skill(db_session, name=selected.name, is_public=True)
    set_skill_installation_policy(default, SkillInstallationPolicy.DEFAULT, db_session)
    assert not skill_user_states(user, [default.id], db_session)[default.id].enabled

    replace_skill_shares(
        skill=selected, user_shares={}, group_shares={}, db_session=db_session
    )
    assert skill_user_states(user, [default.id], db_session)[default.id].enabled
    runtime_ids = {
        skill.id
        for skill in list_runtime_skills_for_user(user=user, db_session=db_session)
    }
    assert default.id in runtime_ids
    assert selected.id not in runtime_ids
    preference = db_session.get(UserSkillPreference, (user.id, selected.id))
    assert preference is not None and preference.enabled

    # Restoring access restores the saved selection without enabling both skills.
    if share_via_group:
        share_skill_with_group(db_session, selected, group)
    else:
        share_skill_with_user(db_session, selected, user)
    states = skill_user_states(user, [default.id, selected.id], db_session)
    assert states[selected.id].enabled
    assert not states[default.id].enabled


def test_replacement_clears_inaccessible_selection_and_effective_default(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    owner = make_user(db_session)
    previous = make_skill(db_session, is_public=False, author_user_id=owner.id)
    share_skill_with_user(db_session, previous, user)
    set_skill_enabled_for_user(
        skill_id=previous.id, enabled=True, user=user, db_session=db_session
    )
    default = make_skill(db_session, name=previous.name, is_public=True)
    replacement = make_skill(db_session, name=previous.name, is_public=True)
    set_skill_installation_policy(default, SkillInstallationPolicy.DEFAULT, db_session)
    replace_skill_shares(
        skill=previous, user_shares={}, group_shares={}, db_session=db_session
    )
    assert skill_user_states(user, [default.id], db_session)[default.id].enabled
    set_skill_enabled_for_user(
        skill_id=replacement.id,
        enabled=True,
        replace_conflict=True,
        user=user,
        db_session=db_session,
    )
    for skill in (previous, default):
        preference = db_session.get(UserSkillPreference, (user.id, skill.id))
        assert preference is not None and not preference.enabled
    set_skill_enabled_for_user(
        skill_id=replacement.id, enabled=False, user=user, db_session=db_session
    )
    share_skill_with_user(db_session, previous, user)
    assert not any(
        state.enabled
        for state in skill_user_states(
            user, [previous.id, default.id, replacement.id], db_session
        ).values()
    )


def test_creation_does_not_displace_default_skill(db_session: Session) -> None:
    user = make_user(db_session)
    default = make_skill(db_session, is_public=True)
    set_skill_installation_policy(default, SkillInstallationPolicy.DEFAULT, db_session)
    new = make_skill(db_session, name=default.name, author_user_id=user.id)
    assert not enable_new_skill_if_name_available__no_commit(new, user.id, db_session)
    assert db_session.get(UserSkillPreference, (user.id, new.id)) is None
    assert skill_user_states(user, [default.id], db_session)[default.id].enabled


def test_toggle_lock_allows_concurrent_share_foreign_key_read(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    toggled = make_skill(db_session, is_public=True)
    shared = make_skill(db_session, is_public=True)
    db_session.commit()
    set_skill_enabled_for_user(
        skill_id=toggled.id, enabled=True, user=user, db_session=db_session
    )
    # Keep the toggle transaction open while another request inserts a direct share.
    with Session(bind=db_session.get_bind()) as sharing_session:
        sharing_session.execute(text("SET LOCAL lock_timeout = '1s'"))
        sharing_session.add(
            Skill__User(
                skill_id=shared.id,
                user_id=user.id,
                permission=SkillSharePermission.VIEWER,
            )
        )
        sharing_session.flush()


def test_creation_serializes_with_toggle_preference_writes(db_session: Session) -> None:
    user = make_user(db_session)
    existing = make_skill(db_session, is_public=True)
    db_session.commit()
    new = make_skill(db_session, name=existing.name, author_user_id=user.id)
    assert enable_new_skill_if_name_available__no_commit(new, user.id, db_session)
    # A toggle cannot pass its user lock while creation's preference is uncommitted.
    with Session(bind=db_session.get_bind()) as toggle_session:
        toggle_session.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError, match="lock timeout") as locked:
            set_skill_enabled_for_user(
                skill_id=existing.id, enabled=True, user=user, db_session=toggle_session
            )
        assert locked.value.statement is not None
        assert "FOR NO KEY UPDATE" in locked.value.statement
    db_session.commit()
    with Session(bind=db_session.get_bind()) as toggle_session:
        with pytest.raises(OnyxError) as error:
            set_skill_enabled_for_user(
                skill_id=existing.id, enabled=True, user=user, db_session=toggle_session
            )
        assert error.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT


def test_ownerless_public_skill_requires_owner_before_becoming_private(
    db_session: Session,
) -> None:
    skill = make_skill(db_session, is_public=True)
    with pytest.raises(OnyxError, match="Assign an owner"):
        set_skill_public_permission(
            skill=skill, public_permission=None, db_session=db_session
        )
    assert skill.public_permission == SkillSharePermission.VIEWER
