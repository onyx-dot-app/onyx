from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from onyx.db.enums import Permission, SkillAccessLevel, SkillSharePermission
from onyx.db.models import Skill, User
from onyx.db.plugin_access import PluginAccess, PluginGroupShare, PluginUserShare
from onyx.db.skill import ensure_can_edit_org_visibility
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.response_helpers import user_permission_for_skill


def _user(*, is_admin: bool = False) -> User:
    """Scoped-manager reach is passed per call via `managed_user_group_ids`,
    never carried on the user."""
    granted = [Permission.BASIC_ACCESS.value]
    if is_admin:
        granted.append(Permission.FULL_ADMIN_PANEL_ACCESS.value)
    return User(
        id=uuid4(),
        email=f"{uuid4().hex}@example.com",
        effective_permissions=granted,
    )


@dataclass
class _Case:
    """A custom skill and its plugin grants."""

    skill: Skill
    published: bool
    user_shares: list[PluginUserShare] = field(default_factory=list)
    group_shares: list[PluginGroupShare] = field(default_factory=list)

    def access(self) -> PluginAccess:
        return PluginAccess(
            plugin_id=self.skill.id,
            author_user_id=self.skill.author_user_id,
            author_email="author@example.com",
            author_is_active=True,
            published=self.published,
            installation_policy=None,
            current_version_id=self.skill.id,
            current_version_number=1,
            published_version_number=1 if self.published else None,
            pending_version_number=None,
            version_user_runs=self.skill.id,
            name=self.skill.name,
            description=self.skill.description,
            is_valid=True,
            user_shares=tuple(self.user_shares),
            group_shares=tuple(self.group_shares),
        )


def _skill(
    author: User,
    *,
    is_public: bool = False,
    public_permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> _Case:
    """``public_permission`` is the legacy organization level. A published
    plugin gives the organization view access only, whatever it was."""
    skill = Skill(
        id=uuid4(),
        name=f"skill-{uuid4().hex}",
        description="Description",
        author_user_id=author.id,
        public_permission=public_permission if is_public else None,
    )
    return _Case(skill=skill, published=is_public)


def _share_with_user(
    case: _Case,
    user_id: UUID | None = None,
    permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> None:
    case.user_shares = [
        PluginUserShare(
            user_id=user_id or uuid4(),
            email="recipient@example.com",
            permission=permission,
        )
    ]


def _share_with_groups(
    case: _Case,
    group_ids: list[int],
    permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> None:
    case.group_shares = [
        PluginGroupShare(group_id=group_id, group_name="group", permission=permission)
        for group_id in group_ids
    ]


def _permission(
    case: _Case,
    user: User,
    user_group_ids: set[int],
    managed_user_group_ids: set[int] | None = None,
) -> SkillAccessLevel | None:
    return user_permission_for_skill(
        case.skill, case.access(), user, user_group_ids, managed_user_group_ids
    )


def test_author_retains_owner_permission_after_sharing() -> None:
    author = _user()
    private_shared = _skill(author)
    _share_with_user(private_shared)

    assert _permission(private_shared, author, set()) == SkillAccessLevel.OWNER
    assert (
        _permission(_skill(author, is_public=True), author, set())
        == SkillAccessLevel.OWNER
    )


def test_admin_can_edit_custom_skill_regardless_of_share_state() -> None:
    author = _user()
    admin = _user(is_admin=True)

    assert _permission(_skill(author), admin, set()) == SkillAccessLevel.EDITOR

    shared = _skill(author)
    _share_with_user(shared)
    assert _permission(shared, admin, set()) == SkillAccessLevel.EDITOR
    assert (
        _permission(_skill(author, is_public=True), admin, set())
        == SkillAccessLevel.EDITOR
    )


def test_viewer_grants_do_not_grant_editor() -> None:
    author = _user()
    basic = _user()

    direct_viewer = _skill(author)
    _share_with_user(direct_viewer, basic.id, SkillSharePermission.VIEWER)
    assert _permission(direct_viewer, basic, set()) == SkillAccessLevel.VIEWER

    group_viewer = _skill(author)
    _share_with_groups(group_viewer, [1], SkillSharePermission.VIEWER)
    assert _permission(group_viewer, basic, {1}) == SkillAccessLevel.VIEWER

    org_viewer = _skill(
        author,
        is_public=True,
        public_permission=SkillSharePermission.VIEWER,
    )
    assert _permission(org_viewer, basic, set()) == SkillAccessLevel.VIEWER


def test_organization_editor_row_gives_view_only() -> None:
    """There is no organization-wide edit: a published skill whose legacy row
    says organization EDITOR is view-only for the organization."""
    author = _user()
    basic = _user()

    assert (
        _permission(
            _skill(
                author,
                is_public=True,
                public_permission=SkillSharePermission.EDITOR,
            ),
            basic,
            set(),
        )
        == SkillAccessLevel.VIEWER
    )


def test_editor_grants_from_direct_or_group_share_grant_editor() -> None:
    author = _user()
    basic = _user()

    direct_editor = _skill(author)
    _share_with_user(direct_editor, basic.id, SkillSharePermission.EDITOR)
    assert _permission(direct_editor, basic, set()) == SkillAccessLevel.EDITOR

    group_editor = _skill(author)
    _share_with_groups(group_editor, [1], SkillSharePermission.EDITOR)
    assert _permission(group_editor, basic, {1}) == SkillAccessLevel.EDITOR


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
        _permission(direct_editor_group_viewer, basic, {1}) == SkillAccessLevel.EDITOR
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
        _permission(direct_viewer_group_editor, basic, {1}) == SkillAccessLevel.EDITOR
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
        _permission(public_viewer_direct_editor, basic, set())
        == SkillAccessLevel.EDITOR
    )


def test_curator_viewer_access_does_not_grant_editor() -> None:
    author = _user()
    curator = _user()

    public_skill = _skill(author, is_public=True)
    assert (
        _permission(
            public_skill,
            curator,
            user_group_ids=set(),
            managed_user_group_ids=set(),
        )
        == SkillAccessLevel.VIEWER
    )

    direct_shared = _skill(author)
    _share_with_user(direct_shared, curator.id)
    assert (
        _permission(
            direct_shared,
            curator,
            user_group_ids=set(),
            managed_user_group_ids=set(),
        )
        == SkillAccessLevel.VIEWER
    )


def test_curator_can_edit_skill_shared_with_curated_groups() -> None:
    author = _user()
    curator = _user()
    skill = _skill(author)
    _share_with_groups(skill, [1])

    assert (
        _permission(
            skill,
            curator,
            user_group_ids={1},
            managed_user_group_ids={1},
        )
        == SkillAccessLevel.EDITOR
    )


def test_curator_cannot_edit_skill_shared_outside_curated_groups() -> None:
    author = _user()
    curator = _user()
    skill = _skill(author)
    _share_with_groups(skill, [1, 2])

    assert (
        _permission(
            skill,
            curator,
            user_group_ids={1},
            managed_user_group_ids={1},
        )
        == SkillAccessLevel.VIEWER
    )


def test_group_membership_alone_does_not_grant_editor() -> None:
    """The old GLOBAL_CURATOR role let mere membership curate; the permission
    system requires the group be one the user *manages*."""
    author = _user()
    member = _user()
    skill = _skill(author)
    _share_with_groups(skill, [1, 2])

    assert (
        _permission(
            skill,
            member,
            user_group_ids={1, 2},
        )
        == SkillAccessLevel.VIEWER
    )


def test_curator_editor_cannot_edit_org_visibility() -> None:
    author = _user()
    curator = _user()
    skill = _skill(author)
    _share_with_groups(skill, [1])

    with pytest.raises(OnyxError):
        ensure_can_edit_org_visibility(skill.skill, curator)


def test_admin_editor_can_edit_org_visibility() -> None:
    author = _user()
    admin = _user(is_admin=True)
    skill = _skill(author, is_public=True)

    ensure_can_edit_org_visibility(skill.skill, admin)


def test_admin_can_edit_personal_skill_org_visibility() -> None:
    author = _user()
    admin = _user(is_admin=True)

    ensure_can_edit_org_visibility(_skill(author).skill, admin)
