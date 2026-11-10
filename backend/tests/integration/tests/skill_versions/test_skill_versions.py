"""Version history through the production HTTP integration harness; no LLM needed."""

import io
import zipfile
from typing import Literal
from uuid import UUID, uuid4

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.skill_version import VERSION_FILES_NOT_KEPT
from onyx.server.features.skill.models import SkillPatchRequest, SkillUserShareRequest
from onyx.skills.content import read_custom_skill_bundle_bytes
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module", autouse=True)
def reset_version_test_data() -> None:
    reset_all()


def _current_bundle_file(skill_id: UUID, path: str) -> bytes:
    with get_session_with_current_tenant() as db_session:
        skill = db_session.get(Skill, skill_id)
        assert skill is not None
        bundle = read_custom_skill_bundle_bytes(skill)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        return archive.read(path)


def _assert_version_unavailable(
    skill_id: UUID,
    version_id: UUID,
    user: DATestUser,
    detail: str,
) -> None:
    url = f"{API_SERVER_URL}/skills/custom/{skill_id}/versions/{version_id}"
    for method, path in (("GET", url), ("POST", f"{url}/restore")):
        response = client.request(method, path, headers=user.headers)
        assert response.status_code == 404
        assert response.json()["detail"] == detail


@pytest.mark.parametrize("actor_role", ["owner", "editor", "admin"])
def test_history_preview_and_restore(
    basic_user: DATestUser,
    admin_user: DATestUser,
    actor_role: Literal["owner", "editor", "admin"],
) -> None:
    skill = SkillManager.create_from_editor(
        basic_user,
        name=f"history-{uuid4().hex[:8]}",
        description="Original description",
        instructions_markdown="Original instructions",
        upload_bytes=b"original attachment",
        upload_filename="reference.txt",
    )
    actor = basic_user if actor_role == "owner" else admin_user
    if actor_role == "editor":
        actor = UserManager.create(name=f"history_editor_{uuid4().hex[:8]}")
        SkillManager.share(
            skill,
            basic_user,
            user_shares=[
                SkillUserShareRequest(
                    user_id=UUID(actor.id), permission=SkillSharePermission.EDITOR
                )
            ],
        )
    original = SkillManager.list_versions(skill.id, actor)[0]
    assert original.version_number == 1
    assert original.created_by is not None
    assert original.created_by.id == UUID(basic_user.id)
    assert original.created_by.email == basic_user.email
    assert original.created_at.tzinfo is not None
    assert original.is_current and original.has_bundle

    SkillManager.patch_custom(
        skill,
        basic_user,
        SkillPatchRequest(
            description="Updated description",
            instructions_markdown="Updated instructions",
        ),
    )
    SkillManager.upload_files(skill, b"new attachment", "new.txt", basic_user)
    preview = SkillManager.preview_version(skill.id, original.id, actor)
    assert preview.name == skill.name
    assert preview.description == "Original description"
    assert preview.instructions_markdown == "Original instructions"
    assert [(file.path, file.size) for file in preview.files] == [("reference.txt", 19)]
    assert (
        SkillManager.get_editable(skill.id, actor).description == "Updated description"
    )

    restored = SkillManager.restore_version(skill.id, original.id, actor)
    assert restored.description == preview.description
    assert restored.instructions_markdown == preview.instructions_markdown
    assert restored.files == preview.files
    assert _current_bundle_file(skill.id, "reference.txt") == b"original attachment"
    history = SkillManager.list_versions(skill.id, actor)
    assert [version.version_number for version in history] == [4, 3, 2, 1]
    assert [version.is_current for version in history] == [True, False, False, False]
    assert history[0].id != original.id
    assert history[0].created_by is not None
    assert history[0].created_by.id == UUID(actor.id)
    assert history[0].created_at >= original.created_at
    assert (
        SkillManager.get_for_user(skill.id, basic_user).description
        == preview.description
    )

    SkillManager.restore_version(skill.id, history[0].id, actor)
    repeated = SkillManager.list_versions(skill.id, actor)
    assert [version.version_number for version in repeated] == [5, 4, 3, 2, 1]
    assert [version.id for version in repeated[1:]] == [
        version.id for version in history
    ]


def test_restore_prunes_oldest_bundle_but_keeps_restored_content(
    basic_user: DATestUser,
) -> None:
    skill = SkillManager.create_custom(basic_user, description="First description")
    original = SkillManager.list_versions(skill.id, basic_user)[0]
    for number in range(2, 11):
        SkillManager.patch_custom(
            skill, basic_user, SkillPatchRequest(description=f"Description {number}")
        )
    restored = SkillManager.restore_version(skill.id, original.id, basic_user)
    assert restored.description == "First description"
    history = SkillManager.list_versions(skill.id, basic_user)
    assert [version.version_number for version in history] == list(range(11, 0, -1))
    assert sum(version.has_bundle for version in history) == 10
    assert history[-1].id == original.id and not history[-1].has_bundle
    assert (
        SkillManager.preview_version(skill.id, history[0].id, basic_user).description
        == "First description"
    )
    assert (
        SkillManager.get_editable(skill.id, basic_user).description
        == "First description"
    )
    _assert_version_unavailable(
        skill.id, original.id, basic_user, VERSION_FILES_NOT_KEPT
    )
    assert SkillManager.list_versions(skill.id, basic_user) == history


@pytest.mark.parametrize("public", [False, True])
def test_viewers_and_strangers_cannot_read_or_restore_history(
    basic_user: DATestUser, public: bool
) -> None:
    viewer = UserManager.create(name=f"history_viewer_{uuid4().hex[:8]}")
    stranger = UserManager.create(name=f"history_stranger_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(basic_user)
    original = SkillManager.list_versions(skill.id, basic_user)[0]
    SkillManager.patch_custom(
        skill, basic_user, SkillPatchRequest(description="Public current description")
    )
    SkillManager.share(
        skill,
        basic_user,
        public_permission=SkillSharePermission.VIEWER if public else None,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )
    assert (
        SkillManager.preview(skill.id, viewer).description
        == "Public current description"
    )
    for user in (viewer, stranger):
        response = client.get(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/versions", headers=user.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Skill not found"
        _assert_version_unavailable(skill.id, original.id, user, "Skill not found")


def test_version_ids_are_scoped_to_skill_and_private_owner(
    basic_user: DATestUser, admin_user: DATestUser
) -> None:
    own_skill = SkillManager.create_custom(basic_user)
    other_skill = SkillManager.create_custom(admin_user)
    other_version = SkillManager.list_versions(other_skill.id, admin_user)[0]
    for user in (basic_user, admin_user):
        _assert_version_unavailable(
            own_skill.id, other_version.id, user, "Skill version not found"
        )
        _assert_version_unavailable(
            own_skill.id, uuid4(), user, "Skill version not found"
        )
    _assert_version_unavailable(
        other_skill.id, other_version.id, basic_user, "Skill not found"
    )
    response = client.get(
        f"{API_SERVER_URL}/skills/custom/{other_skill.id}/versions",
        headers=basic_user.headers,
    )
    assert response.status_code == 404
    assert len(SkillManager.list_versions(own_skill.id, basic_user)) == 1
