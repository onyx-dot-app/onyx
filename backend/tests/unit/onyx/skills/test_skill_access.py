from uuid import uuid4

import pytest

from onyx.auth.schemas import UserRole
from onyx.db.enums import SkillAccessLevel
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import Skill__User
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import _ensure_can_edit_org_visibility
from onyx.server.features.skill.response_helpers import user_permission_for_skill


def _user(role: UserRole = UserRole.BASIC) -> User:
    return User(id=uuid4(), email=f"{uuid4().hex}@example.com", role=role)


def _skill(
    author: User,
    *,
    is_public: bool = False,
    public_permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> Skill:
    return Skill(
        id=uuid4(),
        slug=f"skill-{uuid4().hex}",
        name="Skill",
        description="Description",
        author_user_id=author.id,
        public_permission=public_permission if is_public else None,
        enabled=True,
    )


def _share_with_user(
    skill: Skill,
    user_id: object | None = None,
    permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> None:
    skill.user_shares = [
        Skill__User(
            skill_id=skill.id,
            user_id=user_id or uuid4(),
            permission=permission,
        )
    ]


def _share_with_groups(
    skill: Skill,
    group_ids: list[int],
    permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> None:
    skill.group_shares = [
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group_id,
            permission=permission,
        )
        for group_id in group_ids
    ]


def test_author_retains_owner_permission_after_sharing() -> None:
    author = _user()
    private_shared = _skill(author)
    _share_with_user(private_shared)

    assert (
        user_permission_for_skill(private_shared, author, set())
        == SkillAccessLevel.OWNER
    )
    assert (
        user_permission_for_skill(_skill(author, is_public=True), author, set())
        == SkillAccessLevel.OWNER
    )


def test_admin_can_edit_custom_skill_regardless_of_share_state() -> None:
    author = _user()
    admin = _user(UserRole.ADMIN)

    assert (
        user_permission_for_skill(_skill(author), admin, set())
        == SkillAccessLevel.EDITOR
    )

    shared = _skill(author)
    _share_with_user(shared)
    assert user_permission_for_skill(shared, admin, set()) == SkillAccessLevel.EDITOR
    assert (
        user_permission_for_skill(_skill(author, is_public=True), admin, set())
        == SkillAccessLevel.EDITOR
    )


def test_viewer_grants_do_not_grant_editor() -> None:
    author = _user()
    basic = _user()

    direct_viewer = _skill(author)
    _share_with_user(direct_viewer, basic.id, SkillSharePermission.VIEWER)
    assert (
        user_permission_for_skill(direct_viewer, basic, set())
        == SkillAccessLevel.VIEWER
    )

    group_viewer = _skill(author)
    _share_with_groups(group_viewer, [1], SkillSharePermission.VIEWER)
    assert (
        user_permission_for_skill(group_viewer, basic, {1}) == SkillAccessLevel.VIEWER
    )

    org_viewer = _skill(
        author,
        is_public=True,
        public_permission=SkillSharePermission.VIEWER,
    )
    assert (
        user_permission_for_skill(org_viewer, basic, set()) == SkillAccessLevel.VIEWER
    )


def test_public_editor_permission_grants_editor() -> None:
    author = _user()
    basic = _user()

    assert (
        user_permission_for_skill(
            _skill(
                author,
                is_public=True,
                public_permission=SkillSharePermission.EDITOR,
            ),
            basic,
            set(),
        )
        == SkillAccessLevel.EDITOR
    )


def test_editor_grants_from_direct_group_or_org_share_grant_editor() -> None:
    author = _user()
    basic = _user()

    direct_editor = _skill(author)
    _share_with_user(direct_editor, basic.id, SkillSharePermission.EDITOR)
    assert (
        user_permission_for_skill(direct_editor, basic, set())
        == SkillAccessLevel.EDITOR
    )

    group_editor = _skill(author)
    _share_with_groups(group_editor, [1], SkillSharePermission.EDITOR)
    assert (
        user_permission_for_skill(group_editor, basic, {1}) == SkillAccessLevel.EDITOR
    )

    org_editor = _skill(
        author,
        is_public=True,
        public_permission=SkillSharePermission.EDITOR,
    )
    assert (
        user_permission_for_skill(org_editor, basic, set()) == SkillAccessLevel.EDITOR
    )


def test_any_editor_grant_wins_over_viewer_grants() -> None:
    author = _user()
    basic = _user()

    direct_editor_group_viewer = _skill(author)
    _share_with_user(
        direct_editor_group_viewer,
        basic.id,
        SkillSharePermission.EDITOR,
    )
    _share_with_groups(
        direct_editor_group_viewer,
        [1],
        SkillSharePermission.VIEWER,
    )
    assert (
        user_permission_for_skill(direct_editor_group_viewer, basic, {1})
        == SkillAccessLevel.EDITOR
    )

    direct_viewer_group_editor = _skill(author)
    _share_with_user(
        direct_viewer_group_editor,
        basic.id,
        SkillSharePermission.VIEWER,
    )
    _share_with_groups(
        direct_viewer_group_editor,
        [1],
        SkillSharePermission.EDITOR,
    )
    assert (
        user_permission_for_skill(direct_viewer_group_editor, basic, {1})
        == SkillAccessLevel.EDITOR
    )

    public_viewer_direct_editor = _skill(
        author,
        is_public=True,
        public_permission=SkillSharePermission.VIEWER,
    )
    _share_with_user(
        public_viewer_direct_editor,
        basic.id,
        SkillSharePermission.EDITOR,
    )
    assert (
        user_permission_for_skill(public_viewer_direct_editor, basic, set())
        == SkillAccessLevel.EDITOR
    )


def test_curator_viewer_access_does_not_grant_editor() -> None:
    author = _user()
    curator = _user(UserRole.CURATOR)

    public_skill = _skill(author, is_public=True)
    assert (
        user_permission_for_skill(
            public_skill,
            curator,
            user_group_ids=set(),
            curated_user_group_ids=set(),
        )
        == SkillAccessLevel.VIEWER
    )

    direct_shared = _skill(author)
    _share_with_user(direct_shared, curator.id)
    assert (
        user_permission_for_skill(
            direct_shared,
            curator,
            user_group_ids=set(),
            curated_user_group_ids=set(),
        )
        == SkillAccessLevel.VIEWER
    )


def test_curator_can_edit_skill_shared_with_curated_groups() -> None:
    author = _user()
    curator = _user(UserRole.CURATOR)
    skill = _skill(author)
    _share_with_groups(skill, [1])

    assert (
        user_permission_for_skill(
            skill,
            curator,
            user_group_ids={1},
            curated_user_group_ids={1},
        )
        == SkillAccessLevel.EDITOR
    )


def test_curator_cannot_edit_skill_shared_outside_curated_groups() -> None:
    author = _user()
    curator = _user(UserRole.CURATOR)
    skill = _skill(author)
    _share_with_groups(skill, [1, 2])

    assert (
        user_permission_for_skill(
            skill,
            curator,
            user_group_ids={1},
            curated_user_group_ids={1},
        )
        == SkillAccessLevel.VIEWER
    )


def test_global_curator_can_edit_skill_shared_with_member_groups() -> None:
    author = _user()
    global_curator = _user(UserRole.GLOBAL_CURATOR)
    skill = _skill(author)
    _share_with_groups(skill, [1, 2])

    assert (
        user_permission_for_skill(
            skill,
            global_curator,
            user_group_ids={1, 2},
        )
        == SkillAccessLevel.EDITOR
    )


def test_curator_editor_cannot_edit_org_visibility() -> None:
    author = _user()
    curator = _user(UserRole.CURATOR)
    skill = _skill(author)
    _share_with_groups(skill, [1])

    with pytest.raises(OnyxError):
        _ensure_can_edit_org_visibility(skill, curator)


def test_admin_editor_can_edit_org_visibility() -> None:
    author = _user()
    admin = _user(UserRole.ADMIN)
    skill = _skill(author, is_public=True)

    _ensure_can_edit_org_visibility(skill, admin)


def test_admin_can_edit_personal_skill_org_visibility() -> None:
    author = _user()
    admin = _user(UserRole.ADMIN)

    _ensure_can_edit_org_visibility(_skill(author), admin)
