from __future__ import annotations

from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill__User
from onyx.db.models import Skill__UserGroup
from onyx.db.skill import replace_skill_shares
from onyx.db.skill import transfer_skill_ownership
from onyx.db.skill import update_skill_fields
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import make_built_in_skill_row
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_group
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_user


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


def test_update_skill_fields_supports_permission_and_enabled_updates(
    db_session: Session,
) -> None:
    skill = make_skill(db_session, is_public=False, enabled=True)

    update_skill_fields(
        skill=skill,
        public_permission=SkillSharePermission.EDITOR,
        enabled=False,
        db_session=db_session,
    )

    assert skill.public_permission == SkillSharePermission.EDITOR
    assert skill.enabled is False

    update_skill_fields(
        skill=skill,
        is_public=False,
        db_session=db_session,
    )

    assert skill.public_permission is None
    assert skill.enabled is False


def test_update_skill_fields_preserves_omitted_fields(db_session: Session) -> None:
    skill = make_skill(db_session, is_public=True, enabled=True)

    updated = update_skill_fields(
        skill=skill,
        enabled=False,
        db_session=db_session,
    )

    assert updated.enabled is False
    assert updated.public_permission == SkillSharePermission.VIEWER

    updated = update_skill_fields(
        skill=skill,
        is_public=False,
        db_session=db_session,
    )

    assert updated.enabled is False
    assert updated.public_permission is None


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


def test_transfer_skill_ownership_adds_previous_owner_editor_share(
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
