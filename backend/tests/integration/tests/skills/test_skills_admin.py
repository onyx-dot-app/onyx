from __future__ import annotations

import io
import zipfile
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
import requests
from sqlalchemy import select

from onyx.auth.schemas import UserRole
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import FileRecord
from onyx.db.models import Skill
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import ENABLE_CRAFT
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.skill import build_minimal_bundle
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.skills.conftest import provision_sandbox_for
from tests.integration.tests.skills.conftest import skills_dir_for_user

# ---------------------------------------------------------------------------
# Markers / helpers
# ---------------------------------------------------------------------------

# Tests asserting on-disk side effects only run when the deployment is local.
# When SANDBOX_BACKEND=kubernetes the push goes to a pod; the host filesystem
# the test process can see is irrelevant.
_requires_local_backend = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.LOCAL or not ENABLE_CRAFT,
    reason=(
        "Skill push on-disk verification requires SANDBOX_BACKEND=local and "
        "ENABLE_CRAFT=true; K8s pushes go to the sandbox pod, not the test host."
    ),
)


def _build_bundle_with_markdown(slug: str, body: str) -> bytes:
    """Bundle whose SKILL.md body contains a grep-able marker."""
    return build_minimal_bundle(
        slug,
        body=f"---\nname: {slug}\ndescription: admin test\n---\n\n{body}",
    )


def _fetch_skill_row(skill_id: UUID) -> Skill | None:
    with get_session_with_current_tenant() as db_session:
        return db_session.execute(
            select(Skill).where(Skill.id == skill_id)
        ).scalar_one_or_none()


def _bundle_blob_exists(bundle_file_id: str) -> bool:
    return get_default_file_store().has_file(
        file_id=bundle_file_id,
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )


def _skill_bundle_blob_ids() -> set[str]:
    """Return the set of all file IDs for SKILL_BUNDLE blobs in the file store."""
    with get_session_with_current_tenant() as db_session:
        rows = (
            db_session.execute(
                select(FileRecord.file_id).where(
                    FileRecord.file_origin == FileOrigin.SKILL_BUNDLE
                )
            )
            .scalars()
            .all()
        )
    return set(rows)


def _snapshot_dir(path: Path) -> dict[str, bytes]:
    """Recursively snapshot relative paths → file bytes under ``path``."""
    if not path.exists():
        return {}
    out: dict[str, bytes] = {}
    for p in path.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(path))] = p.read_bytes()
    return out


# ---------------------------------------------------------------------------
# Existing tests preserved
# ---------------------------------------------------------------------------


def test_create_and_list_skill(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug="test-create")
    assert skill.id is not None
    assert skill.slug == "test-create"
    assert skill.enabled is True

    skills_list = SkillManager.list_all(admin_user)
    custom_slugs = [c["slug"] for c in skills_list["customs"]]
    assert "test-create" in custom_slugs


def test_patch_skill_metadata(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug="patch-test")

    updated = SkillManager.patch_custom(
        skill,
        admin_user,
        name="New Name",
        description="New desc",
        is_public=True,
    )
    assert updated.name == "New Name"
    assert updated.description == "New desc"
    assert updated.is_public is True

    disabled = SkillManager.patch_custom(skill, admin_user, enabled=False)
    assert disabled.enabled is False


def test_replace_bundle(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug="bundle-test")
    new_bundle = build_minimal_bundle("bundle-test")
    updated = SkillManager.replace_bundle(skill, new_bundle, admin_user)
    assert updated.slug == "bundle-test"


def test_delete_skill(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug="delete-test")
    SkillManager.delete_custom(skill, admin_user)

    skills_list = SkillManager.list_all(admin_user)
    custom_slugs = [c["slug"] for c in skills_list["customs"]]
    assert "delete-test" not in custom_slugs


def test_duplicate_slug_rejected(admin_user: DATestUser) -> None:
    SkillManager.create_custom(admin_user, slug="dupe-slug")
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(admin_user, slug="dupe-slug")
    assert exc_info.value.response.status_code == 409


def test_bundle_missing_skill_md(admin_user: DATestUser) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no skill.md here")
    bad_bundle = buf.getvalue()

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(
            admin_user, slug="bad-bundle", bundle_bytes=bad_bundle
        )
    assert exc_info.value.response.status_code == 400


def test_bundle_with_template_rejected(admin_user: DATestUser) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: t\ndescription: t\n---\nok")
        zf.writestr("SKILL.md.template", "should not be here")
    bad_bundle = buf.getvalue()

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(
            admin_user, slug="template-bundle", bundle_bytes=bad_bundle
        )
    assert exc_info.value.response.status_code == 400


def test_grants_replace(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug="grants-test", is_public=False)
    updated = SkillManager.replace_grants(skill, [], admin_user)
    assert updated.granted_group_ids == []


def test_patch_slug_to_duplicate(admin_user: DATestUser) -> None:
    SkillManager.create_custom(admin_user, slug="slug-a")
    skill_b = SkillManager.create_custom(admin_user, slug="slug-b")

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.patch_custom(skill_b, admin_user, slug="slug-a")
    assert exc_info.value.response.status_code == 409


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_skill_201_persists_row_grants_bundle(
    admin_user: DATestUser,
) -> None:
    """POST → row persisted with bundle blob and grants visible in DB."""
    group = UserGroupManager.create(admin_user, name="create-grants-group")

    slug = f"persist-{uuid4().hex[:8]}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        is_public=False,
        group_ids=[group.id],
    )

    assert skill.id is not None
    assert skill.granted_group_ids == [group.id]

    row = _fetch_skill_row(skill.id)
    assert row is not None, "skill row missing after create"
    assert row.slug == slug
    assert row.is_public is False
    assert row.enabled is True
    assert row.bundle_file_id, "skill row has no bundle_file_id"
    assert _bundle_blob_exists(row.bundle_file_id), (
        f"bundle blob {row.bundle_file_id} not present in file store after create"
    )


@_requires_local_backend
def test_create_skill_triggers_push_pipeline(admin_user: DATestUser) -> None:
    """Single HTTP-level check that the push pipeline fires after POST.

    The matrix of who-gets-what lives in the push pipeline tests; here we just observe that
    *something* lands on disk for an `is_public=True` skill targeting the
    admin's own sandbox.
    """
    provision_sandbox_for(admin_user)

    slug = f"push-fires-{uuid4().hex[:8]}"
    marker = f"PUSH-MARKER-{uuid4().hex}"
    SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, marker),
        is_public=True,
    )

    skill_md = skills_dir_for_user(admin_user, slug) / "SKILL.md"
    assert skill_md.exists(), (
        f"SKILL.md did not land at {skill_md} — push pipeline did not fire"
    )
    assert marker in skill_md.read_text()


def test_create_skill_rejects_invalid_slug(admin_user: DATestUser) -> None:
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(admin_user, slug="Invalid_Slug")
    assert exc_info.value.response.status_code == 400


def test_create_skill_rejects_reserved_slug(admin_user: DATestUser) -> None:
    reserved = "company-search"
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(admin_user, slug=reserved)
    response = exc_info.value.response
    assert response.status_code == 400
    body = response.json()
    detail = str(body.get("detail") or body)
    assert reserved in detail, (
        f"error message must name the reserved slug; got {detail!r}"
    )


def test_create_skill_409_on_duplicate_slug(admin_user: DATestUser) -> None:
    slug = f"dup-409-{uuid4().hex[:8]}"
    SkillManager.create_custom(admin_user, slug=slug)
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(admin_user, slug=slug)
    assert exc_info.value.response.status_code == 409


def test_create_skill_400_on_invalid_bundle_zip(admin_user: DATestUser) -> None:
    corrupt = b"this is not a zip file at all"
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(
            admin_user,
            slug=f"corrupt-{uuid4().hex[:8]}",
            bundle_bytes=corrupt,
        )
    assert exc_info.value.response.status_code == 400


def test_create_skill_413_on_oversized_bundle(admin_user: DATestUser) -> None:
    """An oversized bundle is rejected with 413.

    The skill-bundle validator enforces a per-file cap of 25 MiB. A single
    26 MiB highly-compressible file exceeds that limit but compresses to
    ~25 KB with ZIP_DEFLATED, so the multipart upload is tiny and passes
    the HTTP parser without issue. The validator's streaming size check
    sees the uncompressed size and raises ``PAYLOAD_TOO_LARGE`` (413).
    """
    oversized_payload = b"A" * (26 * 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: huge\ndescription: huge\n---\nbody\n",
        )
        zf.writestr("big.bin", oversized_payload)
    big_bundle = buf.getvalue()

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(
            admin_user,
            slug=f"too-big-{uuid4().hex[:8]}",
            bundle_bytes=big_bundle,
        )
    assert exc_info.value.response.status_code == 413


def test_create_skill_failure_cleans_up_orphan_blob(
    admin_user: DATestUser,
) -> None:
    """Force the DB step to fail post-blob-write; verify the blob is gone.

    The cheapest reproducible "DB fails after blob written" is a duplicate
    slug: the first create succeeds (and persists a blob), the second create
    is forced to validate + write its own blob and *then* hits the unique
    constraint on slug at the DB layer — the rollback path must delete the
    new blob (regression for SHA `d45bbe1b15`).

    We observe the orphan-cleanup by snapshotting the file store before and
    after the failing call, asserting the set of skill-bundle file ids did
    not grow.
    """
    slug = f"orphan-{uuid4().hex[:8]}"

    # First create — succeeds and saves blob #1.
    first = SkillManager.create_custom(admin_user, slug=slug)
    first_row = _fetch_skill_row(first.id) if first.id is not None else None
    assert first_row is not None
    first_blob_id = first_row.bundle_file_id

    # Snapshot file store blobs before the failing create.
    blobs_before = _skill_bundle_blob_ids()

    # Second create — bundle is fine, but the DB insert fails on the
    # unique-slug check after the blob has already been written. The except
    # branch should delete the just-written blob before re-raising.
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(admin_user, slug=slug)
    assert exc_info.value.response.status_code == 409

    # First skill's blob is untouched.
    assert _bundle_blob_exists(first_blob_id), (
        "first skill's blob should be intact after the failing duplicate create"
    )

    # The orphan blob was cleaned up from the file store: no new blob IDs
    # appeared after the failing create.
    blobs_after = _skill_bundle_blob_ids()
    orphan_blobs = blobs_after - blobs_before
    assert not orphan_blobs, (
        f"Orphan blob(s) leaked into the file store: {orphan_blobs}"
    )

    # And the failing create's blob was cleaned up: the only skill row for
    # this slug is the original, and its blob is the only one tied to it.
    # We assert by counting Skill rows with this slug.
    with get_session_with_current_tenant() as db_session:
        rows = (
            db_session.execute(select(Skill).where(Skill.slug == slug)).scalars().all()
        )
    assert len(rows) == 1, (
        f"expected exactly one skill row with slug {slug}; got {len(rows)}"
    )
    assert rows[0].bundle_file_id == first_blob_id


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------


@_requires_local_backend
def test_patch_visibility_pushes_to_union_of_pre_and_post_affected_users(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Public → private granted to a group → users in the group keep the
    skill, users outside the group lose it.

    We materialise sandboxes for both users, publish a public skill (lands
    on both), then patch it to private with a grant covering only one user
    — the unaffected user's sandbox should lose the skill, the granted
    user's sandbox should keep it.
    """
    provision_sandbox_for(admin_user)
    provision_sandbox_for(basic_user)

    slug = f"visibility-{uuid4().hex[:8]}"
    marker = f"VIS-{uuid4().hex}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, marker),
        is_public=True,
    )

    admin_skill_md = skills_dir_for_user(admin_user, slug) / "SKILL.md"
    basic_skill_md = skills_dir_for_user(basic_user, slug) / "SKILL.md"
    assert admin_skill_md.exists(), "precondition: admin sandbox missing skill"
    assert basic_skill_md.exists(), "precondition: basic sandbox missing skill"

    # Create a group with only basic_user, grant the skill to that group,
    # then flip to private. Admin is NOT in the group, so the skill should
    # disappear from admin's sandbox; basic_user keeps it.
    group = UserGroupManager.create(
        admin_user,
        name=f"vis-{uuid4().hex[:6]}",
        user_ids=[basic_user.id],
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[group],
    )

    SkillManager.patch_custom(skill, admin_user, is_public=False)
    SkillManager.replace_grants(skill, [group.id], admin_user)

    assert basic_skill_md.exists(), (
        "granted user should still have the skill after visibility narrowing"
    )
    assert not admin_skill_md.exists(), (
        "non-granted user should lose the skill after visibility narrowing"
    )


@_requires_local_backend
def test_description_only_patch_leaves_user_sandboxes_unchanged(
    admin_user: DATestUser,
) -> None:
    """A description-only PATCH must not rewrite any sandbox file."""
    provision_sandbox_for(admin_user)

    slug = f"desc-only-{uuid4().hex[:8]}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        is_public=True,
    )

    skill_dir = skills_dir_for_user(admin_user, slug)
    assert skill_dir.exists(), "precondition: skill dir should exist after create"

    before = _snapshot_dir(skill_dir)
    assert before, "precondition: skill dir snapshot is empty"

    SkillManager.patch_custom(skill, admin_user, description="something entirely new")

    after = _snapshot_dir(skill_dir)
    assert after == before, (
        "description-only PATCH should not have rewritten any sandbox files"
    )


def test_patch_slug_409_on_collision(admin_user: DATestUser) -> None:
    SkillManager.create_custom(admin_user, slug="patch-collide-a")
    skill_b = SkillManager.create_custom(admin_user, slug="patch-collide-b")

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.patch_custom(skill_b, admin_user, slug="patch-collide-a")
    assert exc_info.value.response.status_code == 409


@_requires_local_backend
def test_patch_enabled_false_removes_from_all_sandboxes(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    provision_sandbox_for(admin_user)
    provision_sandbox_for(basic_user)

    slug = f"disable-all-{uuid4().hex[:8]}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, "disable-me"),
        is_public=True,
    )

    admin_skill = skills_dir_for_user(admin_user, slug)
    basic_skill = skills_dir_for_user(basic_user, slug)
    assert admin_skill.exists()
    assert basic_skill.exists()

    SkillManager.patch_custom(skill, admin_user, enabled=False)

    assert not admin_skill.exists(), "admin sandbox should not see disabled skill"
    assert not basic_skill.exists(), "basic sandbox should not see disabled skill"


# ---------------------------------------------------------------------------
# Replace bundle
# ---------------------------------------------------------------------------


@_requires_local_backend
def test_replace_bundle_swaps_content_and_pushes(admin_user: DATestUser) -> None:
    """PUT bundle → old blob deleted post-commit, new content on disk."""
    provision_sandbox_for(admin_user)

    slug = f"replace-{uuid4().hex[:8]}"
    old_marker = f"OLD-{uuid4().hex}"
    new_marker = f"NEW-{uuid4().hex}"

    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, old_marker),
        is_public=True,
    )
    assert skill.id is not None
    initial_row = _fetch_skill_row(skill.id)
    assert initial_row is not None
    old_blob_id = initial_row.bundle_file_id

    SkillManager.replace_bundle(
        skill,
        _build_bundle_with_markdown(slug, new_marker),
        admin_user,
    )

    refreshed = _fetch_skill_row(skill.id)
    assert refreshed is not None
    new_blob_id = refreshed.bundle_file_id
    assert new_blob_id != old_blob_id, "bundle_file_id should rotate"
    assert _bundle_blob_exists(new_blob_id)
    assert not _bundle_blob_exists(old_blob_id), (
        "old blob should be deleted after successful replace commit"
    )

    skill_md = skills_dir_for_user(admin_user, slug) / "SKILL.md"
    assert skill_md.exists()
    text = skill_md.read_text()
    assert new_marker in text
    assert old_marker not in text


@_requires_local_backend
def test_replace_bundle_400_on_invalid(admin_user: DATestUser) -> None:
    """A failing replace must leave the old bundle active on disk + in DB."""
    provision_sandbox_for(admin_user)

    slug = f"replace-bad-{uuid4().hex[:8]}"
    marker = f"KEEP-{uuid4().hex}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, marker),
        is_public=True,
    )
    assert skill.id is not None
    original_row = _fetch_skill_row(skill.id)
    assert original_row is not None
    original_blob_id = original_row.bundle_file_id

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.replace_bundle(skill, b"not a zip", admin_user)
    assert exc_info.value.response.status_code == 400

    # Old bundle is still active.
    after_row = _fetch_skill_row(skill.id)
    assert after_row is not None
    assert after_row.bundle_file_id == original_blob_id
    assert _bundle_blob_exists(original_blob_id)

    skill_md = skills_dir_for_user(admin_user, slug) / "SKILL.md"
    assert skill_md.exists()
    assert marker in skill_md.read_text()


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------


def test_replace_grants_400_on_unknown_group_id(admin_user: DATestUser) -> None:
    """Unknown group id → 400 with a message that names the failure mode.

    Regression for SHA `c5e427ceab`: FK violations must surface as a 400
    INVALID_INPUT, not a 500.
    """
    skill = SkillManager.create_custom(
        admin_user, slug=f"unknown-grp-{uuid4().hex[:8]}", is_public=False
    )

    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.replace_grants(skill, [10_000_000], admin_user)

    response = exc_info.value.response
    assert response.status_code == 400
    body = response.json()
    detail = str(body.get("detail") or body)
    assert "group" in detail.lower(), (
        f"error detail must mention groups; got {detail!r}"
    )


@_requires_local_backend
def test_replace_grants_pushes_to_union(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Add group → newly-granted users get file; remove → lose it."""
    provision_sandbox_for(basic_user)

    slug = f"grant-union-{uuid4().hex[:8]}"
    marker = f"GRANT-{uuid4().hex}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, marker),
        is_public=False,
    )

    skill_md = skills_dir_for_user(basic_user, slug) / "SKILL.md"
    assert not skill_md.exists(), (
        "precondition: private skill with no grant should not be on basic's disk"
    )

    group = UserGroupManager.create(
        admin_user,
        name=f"grant-{uuid4().hex[:6]}",
        user_ids=[admin_user.id],
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[group],
    )
    UserGroupManager.add_users(group, [basic_user.id], admin_user)

    SkillManager.replace_grants(skill, [group.id], admin_user)
    assert skill_md.exists(), "basic user should now see skill after grant"

    SkillManager.replace_grants(skill, [], admin_user)
    assert not skill_md.exists(), "basic user should lose skill after grants cleared"


@_requires_local_backend
def test_replace_grants_empty_list_revokes_all(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Set ``group_ids=[]`` on a private skill → all granted users lose it."""
    provision_sandbox_for(basic_user)

    slug = f"revoke-all-{uuid4().hex[:8]}"
    marker = f"REV-{uuid4().hex}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, marker),
        is_public=False,
    )

    group = UserGroupManager.create(
        admin_user,
        name=f"revoke-{uuid4().hex[:6]}",
        user_ids=[admin_user.id],
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[group],
    )
    UserGroupManager.add_users(group, [basic_user.id], admin_user)
    SkillManager.replace_grants(skill, [group.id], admin_user)

    skill_md = skills_dir_for_user(basic_user, slug) / "SKILL.md"
    assert skill_md.exists(), "precondition: basic user should have skill via grant"

    updated = SkillManager.replace_grants(skill, [], admin_user)
    assert updated.granted_group_ids == []
    assert not skill_md.exists(), (
        "basic user should lose skill after grants set to empty list"
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@_requires_local_backend
def test_delete_skill_removes_db_blob_and_pushes(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """After DELETE: row gone, blob gone, granted user's sandbox dir gone."""
    provision_sandbox_for(basic_user)

    slug = f"delete-pipeline-{uuid4().hex[:8]}"
    marker = f"DEL-{uuid4().hex}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=_build_bundle_with_markdown(slug, marker),
        is_public=True,
    )
    assert skill.id is not None
    row = _fetch_skill_row(skill.id)
    assert row is not None
    blob_id = row.bundle_file_id

    skill_dir = skills_dir_for_user(basic_user, slug)
    assert skill_dir.exists(), "precondition: skill dir should exist before delete"

    SkillManager.delete_custom(skill, admin_user)

    assert _fetch_skill_row(skill.id) is None, "skill row should be deleted"
    assert not _bundle_blob_exists(blob_id), "blob should be deleted"
    assert not skill_dir.exists(), (
        "granted user's skill dir should be gone after delete"
    )


def test_delete_skill_404_for_nonexistent(admin_user: DATestUser) -> None:
    bogus_id = uuid4()
    response = requests.delete(
        f"{API_SERVER_URL}/admin/skills/custom/{bogus_id}",
        headers=admin_user.headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_non_admin_returns_403_on_post(basic_user: DATestUser) -> None:
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(basic_user, slug=f"forbid-{uuid4().hex[:6]}")
    assert exc_info.value.response.status_code == 403


def test_non_admin_returns_403_on_admin_list(basic_user: DATestUser) -> None:
    response = requests.get(
        f"{API_SERVER_URL}/admin/skills",
        headers=basic_user.headers,
    )
    assert response.status_code == 403


def test_curator_can_post_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Curators are accepted by the admin-skills endpoints.

    Pins current behavior — see `craft-risks.md` §2.4.
    """
    curator = UserManager.set_role(
        user_to_set=basic_user,
        target_role=UserRole.CURATOR,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    skill = SkillManager.create_custom(
        curator, slug=f"curator-create-{uuid4().hex[:6]}"
    )
    assert skill.id is not None
    assert skill.enabled is True
