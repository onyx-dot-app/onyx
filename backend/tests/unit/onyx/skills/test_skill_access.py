from uuid import UUID
from uuid import uuid4

from onyx.auth.schemas import UserRole
from onyx.db.enums import SkillAccessLevel
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import Skill__User
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.server.features.skill.response_helpers import user_permission_for_skill


def _user(role: UserRole = UserRole.BASIC) -> User:
    return User(id=uuid4(), email=f"{uuid4().hex}@example.com", role=role)


def _skill(
    author: User,
    *,
    built_in_skill_id: str | None = None,
    public_permission: SkillSharePermission | None = None,
) -> Skill:
    return Skill(
        id=uuid4(),
        slug=f"skill-{uuid4().hex}",
        name="Skill",
        description="Description",
        built_in_skill_id=built_in_skill_id,
        bundle_file_id=None if built_in_skill_id else f"bundle-{uuid4().hex}",
        author_user_id=author.id,
        public_permission=public_permission,
        enabled=True,
    )


def _share_with_user(
    skill: Skill,
    user_id: UUID | None = None,
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


def test_built_in_skills_are_viewer_for_all_users() -> None:
    user = _user()
    skill = _skill(_user(), built_in_skill_id="built-in")

    assert user_permission_for_skill(skill, user, set()) == SkillAccessLevel.VIEWER


def test_author_retains_owner_permission_after_sharing() -> None:
    author = _user()
    skill = _skill(author, public_permission=SkillSharePermission.VIEWER)
    _share_with_user(skill)

    assert user_permission_for_skill(skill, author, set()) == SkillAccessLevel.OWNER


def test_admin_can_edit_custom_skill_regardless_of_share_state() -> None:
    admin = _user(UserRole.ADMIN)
    skill = _skill(_user())

    assert user_permission_for_skill(skill, admin, set()) == SkillAccessLevel.EDITOR


def test_editor_grants_from_direct_group_or_org_share_grant_editor() -> None:
    direct_user = _user()
    direct_editor = _skill(_user())
    _share_with_user(direct_editor, direct_user.id, SkillSharePermission.EDITOR)
    assert (
        user_permission_for_skill(direct_editor, direct_user, set())
        == SkillAccessLevel.EDITOR
    )

    group_user = _user()
    group_editor = _skill(_user())
    _share_with_groups(group_editor, [1], SkillSharePermission.EDITOR)
    assert (
        user_permission_for_skill(group_editor, group_user, {1})
        == SkillAccessLevel.EDITOR
    )

    org_user = _user()
    org_editor = _skill(_user(), public_permission=SkillSharePermission.EDITOR)
    assert (
        user_permission_for_skill(org_editor, org_user, set())
        == SkillAccessLevel.EDITOR
    )


def test_viewer_grants_from_direct_group_or_org_share_grant_viewer() -> None:
    direct_user = _user()
    direct_viewer = _skill(_user())
    _share_with_user(direct_viewer, direct_user.id)
    assert (
        user_permission_for_skill(direct_viewer, direct_user, set())
        == SkillAccessLevel.VIEWER
    )

    group_user = _user()
    group_viewer = _skill(_user())
    _share_with_groups(group_viewer, [1])
    assert (
        user_permission_for_skill(group_viewer, group_user, {1})
        == SkillAccessLevel.VIEWER
    )

    org_user = _user()
    org_viewer = _skill(_user(), public_permission=SkillSharePermission.VIEWER)
    assert (
        user_permission_for_skill(org_viewer, org_user, set())
        == SkillAccessLevel.VIEWER
    )


def test_any_editor_grant_wins_over_viewer_grants() -> None:
    user = _user()
    skill = _skill(_user(), public_permission=SkillSharePermission.VIEWER)
    _share_with_groups(skill, [1], SkillSharePermission.EDITOR)

    assert user_permission_for_skill(skill, user, {1}) == SkillAccessLevel.EDITOR


def test_curator_can_edit_skill_only_when_all_group_shares_are_curated() -> None:
    curator = _user(UserRole.CURATOR)
    managed_skill = _skill(_user())
    _share_with_groups(managed_skill, [1, 2])

    assert (
        user_permission_for_skill(
            managed_skill,
            curator,
            user_group_ids={1, 2},
            curated_user_group_ids={1, 2},
        )
        == SkillAccessLevel.EDITOR
    )

    partially_managed_skill = _skill(_user())
    _share_with_groups(partially_managed_skill, [1, 2])
    assert (
        user_permission_for_skill(
            partially_managed_skill,
            curator,
            user_group_ids={1, 2},
            curated_user_group_ids={1},
        )
        == SkillAccessLevel.VIEWER
    )


def test_global_curator_can_edit_skill_only_when_all_group_shares_are_member_groups() -> (
    None
):
    global_curator = _user(UserRole.GLOBAL_CURATOR)
    managed_skill = _skill(_user())
    _share_with_groups(managed_skill, [1, 2])

    assert (
        user_permission_for_skill(
            managed_skill,
            global_curator,
            user_group_ids={1, 2},
        )
        == SkillAccessLevel.EDITOR
    )

    partially_managed_skill = _skill(_user())
    _share_with_groups(partially_managed_skill, [1, 2])
    assert (
        user_permission_for_skill(
            partially_managed_skill,
            global_curator,
            user_group_ids={1},
        )
        == SkillAccessLevel.VIEWER
    )


def test_unshared_custom_skill_has_no_access_for_non_author() -> None:
    assert user_permission_for_skill(_skill(_user()), _user(), set()) is None
