"""Version list, preview and restore of custom skills."""

from typing import Literal
from uuid import UUID, uuid4

import pytest

from onyx.db.enums import SkillSharePermission
from onyx.server.features.skill.models import SkillPatchRequest, SkillUserShareRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture
def owner() -> DATestUser:
    return UserManager.create(name=f"versions_owner_{uuid4().hex[:8]}")


def _assert_refused(
    skill_id: UUID, version_id: UUID, user: DATestUser, detail: str
) -> None:
    url = f"{API_SERVER_URL}/skills/custom/{skill_id}"
    for response in (
        client.get(f"{url}/versions", headers=user.headers),
        client.get(f"{url}/versions/{version_id}", headers=user.headers),
        SkillManager.restore_version_response(skill_id, version_id, version_id, user),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == detail


@pytest.mark.parametrize("actor_role", ["owner", "editor", "admin"])
def test_list_preview_and_restore(
    owner: DATestUser,
    admin_user: DATestUser,
    actor_role: Literal["owner", "editor", "admin"],
) -> None:
    skill = SkillManager.create_from_editor(
        owner,
        name=f"history-{uuid4().hex[:8]}",
        description="Original description",
        instructions_markdown="Original instructions",
        upload_bytes=b"original attachment",
        upload_filename="reference.txt",
    )
    actor = owner if actor_role == "owner" else admin_user
    if actor_role == "editor":
        actor = UserManager.create(name=f"versions_editor_{uuid4().hex[:8]}")
        SkillManager.share(
            skill,
            owner,
            user_shares=[
                SkillUserShareRequest(
                    user_id=UUID(actor.id), permission=SkillSharePermission.EDITOR
                )
            ],
        )
    SkillManager.patch_custom(
        skill,
        owner,
        SkillPatchRequest(
            description="Updated description",
            instructions_markdown="Updated instructions",
        ),
    )
    SkillManager.upload_files(skill, b"new attachment", "new.txt", owner)

    history = SkillManager.list_versions(skill.id, actor)
    assert [version.version_number for version in history] == [3, 2, 1]
    assert [version.is_current for version in history] == [True, False, False]
    original = history[-1]
    assert original.created_by_email == owner.email
    assert original.created_at.tzinfo is not None

    preview = SkillManager.preview_version(skill.id, original.id, actor)
    assert preview.description == "Original description"
    assert preview.instructions_markdown == "Original instructions"

    restored = SkillManager.restore_version(skill.id, original.id, history[0].id, actor)
    assert restored.description == "Original description"
    assert restored.instructions_markdown == "Original instructions"
    assert [(file.path, file.size) for file in restored.files] == [
        ("reference.txt", 19)
    ]
    assert restored.current_version_number == 4

    after = SkillManager.list_versions(skill.id, actor)
    assert [version.version_number for version in after] == [4, 3, 2, 1]
    assert after[0].id == restored.current_version_id
    assert after[0].created_by_email == actor.email
    assert after[0].is_current
    assert [version.id for version in after[1:]] == [version.id for version in history]
    assert SkillManager.get_for_user(skill.id, owner).description == (
        "Original description"
    )
    assert SkillManager.get_for_user(skill.id, owner).current_version_number == 4


def test_restore_with_a_stale_base_is_refused(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner, description="First")
    SkillManager.patch_custom(skill, owner, SkillPatchRequest(description="Second"))
    current, original = SkillManager.list_versions(skill.id, owner)

    response = SkillManager.restore_version_response(
        skill.id, original.id, original.id, owner
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "PLUGIN_VERSION_STALE"
    assert [version.id for version in SkillManager.list_versions(skill.id, owner)] == [
        current.id,
        original.id,
    ]


def test_restore_of_the_current_content_adds_no_version(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner, description="First")
    SkillManager.patch_custom(skill, owner, SkillPatchRequest(description="Second"))
    current, original = SkillManager.list_versions(skill.id, owner)

    unchanged = SkillManager.restore_version(skill.id, current.id, current.id, owner)
    assert unchanged.current_version_id == current.id
    restored = SkillManager.restore_version(skill.id, original.id, current.id, owner)
    assert restored.current_version_number == 3
    history = SkillManager.list_versions(skill.id, owner)

    again = SkillManager.restore_version(skill.id, original.id, history[0].id, owner)

    assert again.current_version_id == history[0].id
    assert SkillManager.list_versions(skill.id, owner) == history


@pytest.mark.parametrize("published", [False, True])
def test_viewers_cannot_read_or_restore_versions(
    owner: DATestUser, published: bool
) -> None:
    viewer = UserManager.create(name=f"versions_viewer_{uuid4().hex[:8]}")
    stranger = UserManager.create(name=f"versions_stranger_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(owner)
    SkillManager.share(
        skill,
        owner,
        is_public=published or None,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )
    version = SkillManager.list_versions(skill.id, owner)[0]
    assert SkillManager.preview(skill.id, viewer).name == skill.name

    for user in (viewer, stranger):
        _assert_refused(skill.id, version.id, user, "Skill not found")
    assert len(SkillManager.list_versions(skill.id, owner)) == 1


def test_version_of_another_skill_is_not_found(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    own_skill = SkillManager.create_custom(owner)
    other_skill = SkillManager.create_custom(admin_user)
    other_version = SkillManager.list_versions(other_skill.id, admin_user)[0]
    own_version = SkillManager.list_versions(own_skill.id, owner)[0]

    preview = client.get(
        f"{API_SERVER_URL}/skills/custom/{own_skill.id}/versions/{other_version.id}",
        headers=owner.headers,
    )
    restore = SkillManager.restore_version_response(
        own_skill.id, other_version.id, own_version.id, owner
    )

    for response in (preview, restore):
        assert response.status_code == 404
        assert response.json()["detail"] == "Skill version not found."
