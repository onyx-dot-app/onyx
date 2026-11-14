from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from onyx.db.enums import SkillAccessLevel, SkillSharePermission
from onyx.server.features.skill.models import (
    SkillPatchRequest,
    SkillResponse,
    SkillUserShareRequest,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _assert_skill_hidden(skill_id: object, user: DATestUser) -> None:
    response = client.get(
        f"{API_SERVER_URL}/skills/{skill_id}",
        headers=user.headers,
    )
    assert response.status_code == 404


def _assert_edit_hidden(skill_id: object, user: DATestUser) -> None:
    response = client.get(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/edit",
        headers=user.headers,
    )
    assert response.status_code == 404


def _skill_id(skill: SkillResponse) -> UUID:
    return skill.id


def test_edit_fetch_returns_instructions_and_share_details(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    editor = UserManager.create(name=f"skill_editor_{uuid4().hex[:8]}")
    viewer = UserManager.create(name=f"skill_viewer_{uuid4().hex[:8]}")
    stranger = UserManager.create(name=f"skill_stranger_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"edit-fetch-{uuid4().hex[:6]}",
    )
    skill_id = _skill_id(skill)

    shared = SkillManager.share(
        skill,
        basic_user,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(editor.id),
                permission=SkillSharePermission.EDITOR,
            ),
            SkillUserShareRequest(
                user_id=UUID(viewer.id),
                permission=SkillSharePermission.VIEWER,
            ),
        ],
    )
    assert len(shared.user_shares) == 2

    owner_editable = SkillManager.get_editable(skill_id, basic_user)
    assert owner_editable.user_permission == SkillAccessLevel.OWNER
    assert owner_editable.instructions_markdown == "Skill instructions."

    editable = SkillManager.get_editable(skill_id, editor)
    assert editable.id == skill_id
    assert editable.user_permission == SkillAccessLevel.EDITOR
    assert editable.instructions_markdown == "Skill instructions."
    assert {share.permission for share in editable.user_shares} == {
        SkillSharePermission.EDITOR,
        SkillSharePermission.VIEWER,
    }

    _assert_edit_hidden(skill_id, viewer)
    _assert_edit_hidden(skill_id, stranger)


def test_preview_returns_instructions_without_share_details(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    viewer = UserManager.create(name=f"skill_preview_viewer_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"preview-custom-{uuid4().hex[:6]}",
        description="Preview description",
    )
    skill_id = _skill_id(skill)
    SkillManager.share(
        skill,
        basic_user,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id),
                permission=SkillSharePermission.VIEWER,
            )
        ],
    )

    preview = SkillManager.preview(skill_id, viewer)

    assert preview.source == "custom"
    assert preview.id == skill_id
    assert preview.name == skill.name
    assert preview.description == "Preview description"
    assert preview.instructions_markdown == "Skill instructions."
    assert not hasattr(preview, "user_shares")
    assert not hasattr(preview, "group_shares")
    assert not hasattr(preview, "user_permission")


def test_builtin_preview_returns_instructions(basic_user: DATestUser) -> None:
    builtins = SkillManager.list_for_user(basic_user).builtins
    assert builtins

    preview = SkillManager.preview(builtins[0].id, basic_user)

    assert preview.source == "builtin"
    assert preview.id == builtins[0].id
    assert preview.instructions_markdown.strip()


def test_patch_details_rewrites_bundle_without_changing_slug(
    basic_user: DATestUser,
) -> None:
    name = f"patch-details-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(
        basic_user,
        name=name,
        description="Original description",
    )
    skill_id = _skill_id(skill)

    updated = SkillManager.patch_custom(
        skill,
        basic_user,
        SkillPatchRequest(
            description="Updated description",
            instructions_markdown="# Updated instructions\n\nUse the revised workflow.",
        ),
    )

    assert updated.name == name
    assert updated.name == name
    assert updated.description == "Updated description"

    editable = SkillManager.get_editable(skill_id, basic_user)
    assert editable.name == name
    assert editable.description == "Updated description"
    assert editable.instructions_markdown == (
        "# Updated instructions\n\nUse the revised workflow."
    )

    preview = SkillManager.preview(skill_id, basic_user)
    assert preview.name == name
    assert preview.description == "Updated description"
    assert preview.instructions_markdown == (
        "# Updated instructions\n\nUse the revised workflow."
    )


def test_direct_viewer_share_grants_view_not_edit(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    viewer = UserManager.create(name=f"skill_direct_viewer_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"direct-viewer-{uuid4().hex[:6]}",
    )
    skill_id = _skill_id(skill)

    shared = SkillManager.share(
        skill,
        basic_user,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id),
                permission=SkillSharePermission.VIEWER,
            )
        ],
    )

    assert len(shared.user_shares) == 1
    assert str(shared.user_shares[0].user.id) == viewer.id
    assert shared.user_shares[0].user.email == viewer.email
    assert shared.user_shares[0].permission == SkillSharePermission.VIEWER
    visible = SkillManager.get_for_user(str(skill_id), viewer)
    assert visible.user_permission == SkillAccessLevel.VIEWER
    assert visible.is_personal is False
    _assert_edit_hidden(skill_id, viewer)


def test_direct_share_restores_existing_enabled_preference(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    recipient = UserManager.create(name=f"skill_recipient_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"preference-restore-{uuid4().hex[:6]}",
    )
    share = SkillUserShareRequest(
        user_id=UUID(recipient.id),
        permission=SkillSharePermission.VIEWER,
    )

    SkillManager.share(skill, basic_user, user_shares=[share])
    initially_shared = SkillManager.get_for_user(skill.id, recipient)
    assert initially_shared.enabled is False
    assert SkillManager.set_enabled(skill, recipient, True).enabled is True

    SkillManager.share(skill, basic_user, user_shares=[])
    _assert_skill_hidden(skill.id, recipient)

    SkillManager.share(skill, basic_user, user_shares=[share])
    reshared = SkillManager.get_for_user(skill.id, recipient)
    assert reshared.enabled is True


def test_org_wide_editor_permission_is_refused(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    other_user = UserManager.create(name=f"skill_org_editor_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"org-editor-{uuid4().hex[:6]}",
    )
    skill_id = _skill_id(skill)

    public_viewer = SkillManager.share(
        skill,
        basic_user,
        is_public=True,
        public_permission=SkillSharePermission.VIEWER,
    )
    assert public_viewer.public_permission == SkillSharePermission.VIEWER
    _assert_edit_hidden(skill_id, other_user)

    # Editors are named users and groups. The organization can only view.
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.share(
            skill,
            basic_user,
            is_public=True,
            public_permission=SkillSharePermission.EDITOR,
        )
    assert exc_info.value.response.status_code == 400
    assert "edit access" in exc_info.value.response.json()["detail"]
    assert (
        SkillManager.get_for_user(str(skill_id), basic_user).public_permission
        == SkillSharePermission.VIEWER
    )
    _assert_edit_hidden(skill_id, other_user)


def test_published_skill_cannot_be_made_private(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    shared_user = UserManager.create(name=f"skill_scoped_user_{uuid4().hex[:8]}")
    unshared_user = UserManager.create(name=f"skill_unscoped_user_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"scoped-share-{uuid4().hex[:6]}",
    )
    skill_id = _skill_id(skill)

    SkillManager.share(skill, basic_user, is_public=True)
    assert SkillManager.get_for_user(str(skill_id), unshared_user).id == skill_id

    # Publishing is one-way. The whole request is refused, shares included.
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.share(
            skill,
            basic_user,
            is_public=False,
            user_shares=[
                SkillUserShareRequest(
                    user_id=UUID(shared_user.id),
                    permission=SkillSharePermission.VIEWER,
                )
            ],
        )
    assert exc_info.value.response.status_code == 400
    assert "cannot be made private" in exc_info.value.response.json()["detail"]
    after = SkillManager.get_for_user(str(skill_id), basic_user)
    assert after.public_permission == SkillSharePermission.VIEWER
    assert SkillManager.get_for_user(str(skill_id), unshared_user).id == skill_id


def test_owner_transfer_demotes_previous_owner_and_promotes_new_owner(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    new_owner = UserManager.create(name=f"skill_new_owner_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"transfer-owner-{uuid4().hex[:6]}",
    )
    skill_id = _skill_id(skill)
    SkillManager.share(
        skill,
        basic_user,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(new_owner.id),
                permission=SkillSharePermission.VIEWER,
            )
        ],
    )

    old_owner_response = SkillManager.transfer_ownership(
        skill,
        new_owner.id,
        basic_user,
    )

    assert old_owner_response.author_user_id is not None
    assert str(old_owner_response.author_user_id) == new_owner.id
    assert old_owner_response.user_permission == SkillAccessLevel.EDITOR
    assert len(old_owner_response.user_shares) == 1
    assert str(old_owner_response.user_shares[0].user.id) == basic_user.id
    assert old_owner_response.user_shares[0].user.email == basic_user.email
    assert old_owner_response.user_shares[0].permission == SkillSharePermission.EDITOR

    new_owner_response = SkillManager.get_for_user(str(skill_id), new_owner)
    assert new_owner_response.author_user_id == UUID(new_owner.id)
    assert new_owner_response.user_permission == SkillAccessLevel.OWNER
    assert new_owner_response.enabled is False


@pytest.mark.parametrize(
    "permission",
    [SkillSharePermission.VIEWER, SkillSharePermission.EDITOR],
)
def test_sharee_cannot_transfer_ownership(
    basic_user: DATestUser,
    admin_user: DATestUser,  # noqa: ARG001
    permission: SkillSharePermission,
) -> None:
    sharee = UserManager.create(name=f"skill_transfer_sharee_{uuid4().hex[:8]}")
    target = UserManager.create(name=f"skill_transfer_target_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(
        basic_user,
        name=f"transfer-deny-{permission.lower()}-{uuid4().hex[:6]}",
    )
    SkillManager.share(
        skill,
        basic_user,
        user_shares=[
            SkillUserShareRequest(user_id=UUID(sharee.id), permission=permission)
        ],
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.transfer_ownership(skill, target.id, sharee)

    assert exc_info.value.response.status_code == 403


def test_transfer_rejects_missing_and_inactive_targets(
    basic_user: DATestUser,
    admin_user: DATestUser,
) -> None:
    inactive_target = UserManager.create(
        name=f"skill_inactive_target_{uuid4().hex[:8]}"
    )
    inactive_target = UserManager.set_status(
        inactive_target,
        False,
        admin_user,
    )
    skill = SkillManager.create_custom(
        basic_user,
        name=f"transfer-target-{uuid4().hex[:6]}",
    )
    skill_id = _skill_id(skill)

    missing_response = client.post(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/transfer-ownership",
        json={"new_owner_user_id": str(uuid4())},
        headers=basic_user.headers,
    )
    assert missing_response.status_code == 404

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.transfer_ownership(skill, inactive_target.id, basic_user)

    assert exc_info.value.response.status_code == 400


def test_admin_transfers_vacant_skill_but_not_owned_skill(
    admin_user: DATestUser,
) -> None:
    owner = UserManager.create(name=f"skill_transfer_owner_{uuid4().hex[:8]}")
    target = UserManager.create(name=f"skill_admin_target_{uuid4().hex[:8]}")
    owned_skill = SkillManager.create_custom(
        owner,
        name=f"admin-owned-transfer-{uuid4().hex[:6]}",
    )
    owned_skill_id = _skill_id(owned_skill)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.transfer_ownership(owned_skill, target.id, admin_user)
    assert exc_info.value.response.status_code == 403

    inactive_owner = UserManager.set_status(owner, False, admin_user)
    try:
        vacant_response = SkillManager.transfer_ownership(
            owned_skill,
            target.id,
            admin_user,
        )
    finally:
        UserManager.set_status(inactive_owner, True, admin_user)

    assert vacant_response.author_user_id is not None
    assert str(vacant_response.author_user_id) == target.id
    new_owner_response = SkillManager.get_for_user(str(owned_skill_id), target)
    assert new_owner_response.user_permission == SkillAccessLevel.OWNER
