"""Version list, preview and restore of custom skills.

A pruned version is made by emptying its bundle_file_id in the database, as
retention does."""

from collections.abc import Generator
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, update

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import SkillSharePermission
from onyx.db.models import PluginVersion
from onyx.db.plugin import BUNDLES_KEPT, PLUGIN_VERSION_PAGE_SIZE
from onyx.server.features.skill.models import SkillPatchRequest, SkillUserShareRequest
from onyx.skills.content import VERSION_FILES_NOT_KEPT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def owner() -> DATestUser:
    return UserManager.create(name=f"versions_owner_{uuid4().hex[:8]}")


def _prune(version_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(PluginVersion)
            .where(PluginVersion.id == version_id)
            .values(bundle_file_id=None, bundle_sha256=None)
        )
        db_session.commit()


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
    assert original.created_by_user_id == UUID(owner.id)
    assert original.created_by_email == owner.email
    assert original.created_at.tzinfo is not None
    assert original.bundle_kept
    assert original.file_count == 2
    assert original.unpacked_size_bytes is not None
    assert original.unpacked_size_bytes > len(b"original attachment")
    assert history[0].file_count == 3

    preview = SkillManager.preview_version(skill.id, original.id, actor)
    assert preview.id == original.id
    assert preview.version_number == 1
    assert preview.name == skill.name
    assert preview.description == "Original description"
    assert preview.instructions_markdown == "Original instructions"
    assert [(file.path, file.size) for file in preview.files] == [("reference.txt", 19)]

    restored = SkillManager.restore_version(skill.id, original.id, history[0].id, actor)
    assert restored.description == "Original description"
    assert restored.instructions_markdown == "Original instructions"
    assert restored.files == preview.files
    assert restored.current_version_number == 4

    after = SkillManager.list_versions(skill.id, actor)
    assert [version.version_number for version in after] == [4, 3, 2, 1]
    assert after[0].id == restored.current_version_id
    assert after[0].created_by_user_id == UUID(actor.id)
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


def test_pruned_version_previews_from_the_database_and_is_not_restored(
    owner: DATestUser,
) -> None:
    skill = SkillManager.create_from_editor(
        owner,
        name=f"pruned-{uuid4().hex[:8]}",
        description="Kept in the database",
        instructions_markdown="Pruned instructions",
    )
    SkillManager.patch_custom(skill, owner, SkillPatchRequest(description="Newer"))
    current, original = SkillManager.list_versions(skill.id, owner)
    _prune(original.id)

    pruned = SkillManager.list_versions(skill.id, owner)[-1]
    assert not pruned.bundle_kept
    preview = SkillManager.preview_version(skill.id, original.id, owner)
    assert preview.description == "Kept in the database"
    assert preview.instructions_markdown == "Pruned instructions"

    response = SkillManager.restore_version_response(
        skill.id, original.id, current.id, owner
    )
    assert response.status_code == 404
    assert response.json()["detail"] == VERSION_FILES_NOT_KEPT
    assert len(SkillManager.list_versions(skill.id, owner)) == 2


def test_restore_past_the_limit_prunes_the_oldest_bundle(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner, description="Description 1")
    for number in range(2, BUNDLES_KEPT + 1):
        SkillManager.patch_custom(
            skill, owner, SkillPatchRequest(description=f"Description {number}")
        )
    history = SkillManager.list_all_versions(skill.id, owner)
    assert all(version.bundle_kept for version in history)
    second = history[-2]

    restored = SkillManager.restore_version(skill.id, second.id, history[0].id, owner)

    assert restored.description == "Description 2"
    after = SkillManager.list_all_versions(skill.id, owner)
    assert [version.version_number for version in after] == list(
        range(BUNDLES_KEPT + 1, 0, -1)
    )
    assert [version.bundle_kept for version in after] == [True] * BUNDLES_KEPT + [False]
    oldest = SkillManager.preview_version(skill.id, after[-1].id, owner)
    assert oldest.description == "Description 1"


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


def test_list_pages_through_older_versions(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner)
    total = PLUGIN_VERSION_PAGE_SIZE + 5
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            insert(PluginVersion),
            [
                {"id": uuid4(), "plugin_id": skill.id, "version_number": number}
                for number in range(2, total + 1)
            ],
        )
        db_session.commit()

    numbers: list[int] = []
    before_version: int | None = None
    while True:
        page = SkillManager.list_versions(skill.id, owner, before_version)
        if not page:
            break
        assert len(page) <= PLUGIN_VERSION_PAGE_SIZE
        numbers.extend(version.version_number for version in page)
        before_version = page[-1].version_number

    assert numbers == list(range(total, 0, -1))
