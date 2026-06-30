from __future__ import annotations

import io
import zipfile
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.auth.schemas import UserRole
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import FileRecord
from onyx.db.models import Skill
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import SkillPatchRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import build_minimal_bundle
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Existing tests preserved
# ---------------------------------------------------------------------------


def test_create_and_list_skill(admin_user: DATestUser) -> None:
    slug = f"test-create-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(admin_user, slug=slug)
    assert skill.slug == slug
    assert skill.enabled is True

    skills_list = SkillManager.list_all(admin_user)
    custom_slugs = [skill.slug for skill in skills_list.customs]
    assert slug in custom_slugs


def test_patch_skill_metadata(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug=f"patch-test-{uuid4().hex[:6]}")

    public = SkillManager.patch_custom(
        skill, admin_user, SkillPatchRequest(is_public=True)
    )
    assert public.is_public is True

    disabled = SkillManager.patch_custom(
        skill, admin_user, SkillPatchRequest(enabled=False)
    )
    assert disabled.enabled is False


def test_replace_bundle_updates_metadata(admin_user: DATestUser) -> None:
    slug = f"bundle-test-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        name="Original Name",
        description="Original desc",
    )
    new_bundle = build_minimal_bundle(
        slug, name="Renamed via bundle", description="Updated desc"
    )
    updated = SkillManager.replace_bundle(skill, new_bundle, admin_user)
    assert updated.slug == slug
    assert updated.name == "Renamed via bundle"
    assert updated.description == "Updated desc"


def test_delete_skill(admin_user: DATestUser) -> None:
    slug = f"delete-test-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(admin_user, slug=slug)
    SkillManager.delete_custom(skill, admin_user)

    skills_list = SkillManager.list_all(admin_user)
    custom_slugs = [skill.slug for skill in skills_list.customs]
    assert slug not in custom_slugs


def test_bundle_missing_skill_md(admin_user: DATestUser) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no skill.md here")
    bad_bundle = buf.getvalue()

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(
            admin_user, slug=f"bad-bundle-{uuid4().hex[:6]}", bundle_bytes=bad_bundle
        )
    assert exc_info.value.response.status_code == 400


def test_bundle_with_template_rejected(admin_user: DATestUser) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: t\ndescription: t\n---\nok")
        zf.writestr("SKILL.md.template", "should not be here")
    bad_bundle = buf.getvalue()

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(
            admin_user,
            slug=f"template-bundle-{uuid4().hex[:6]}",
            bundle_bytes=bad_bundle,
        )
    assert exc_info.value.response.status_code == 400


def test_group_shares_replace(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(
        admin_user, slug=f"group-shares-test-{uuid4().hex[:6]}", is_public=False
    )
    updated = SkillManager.replace_group_shares(skill, [], admin_user)
    assert updated.group_shares == []


def test_metadata_from_bundle_frontmatter(admin_user: DATestUser) -> None:
    bundle = build_minimal_bundle(
        "from-frontmatter", name="From Bundle", description="From bundle desc"
    )
    skill = SkillManager.create_custom(
        admin_user, slug="from-frontmatter", bundle_bytes=bundle
    )
    assert skill.name == "From Bundle"
    assert skill.description == "From bundle desc"


def test_missing_frontmatter_rejected(admin_user: DATestUser) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "no frontmatter at all\n")
    bad_bundle = buf.getvalue()

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(admin_user, slug="no-fm", bundle_bytes=bad_bundle)
    assert exc_info.value.response.status_code == 400


def test_bad_filename_rejected(admin_user: DATestUser) -> None:
    bundle = build_minimal_bundle("placeholder")
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(
            admin_user,
            slug="placeholder",
            bundle_bytes=bundle,
            filename="Invalid Name.zip",
        )
    assert exc_info.value.response.status_code == 400


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_skill_201_persists_row_group_shares_bundle(
    admin_user: DATestUser,
) -> None:
    """POST -> row persisted with bundle blob and group shares visible in DB."""
    group = UserGroupManager.create(admin_user, name="create-shares-group")

    slug = f"persist-{uuid4().hex[:8]}"
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        is_public=False,
        group_ids=[group.id],
    )

    assert [share.group_id for share in skill.group_shares] == [group.id]

    row = _fetch_skill_row(skill.id)
    assert row is not None, "skill row missing after create"
    assert row.slug == slug
    assert row.is_public is False
    assert row.enabled is True
    assert row.bundle_file_id, "skill row has no bundle_file_id"
    assert _bundle_blob_exists(row.bundle_file_id), (
        f"bundle blob {row.bundle_file_id} not present in file store after create"
    )


def test_create_skill_rejects_invalid_slug(admin_user: DATestUser) -> None:
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(admin_user, slug="Invalid_Slug")
    assert exc_info.value.response.status_code == 400


def test_create_skill_rejects_reserved_slug(admin_user: DATestUser) -> None:
    reserved = "company-search"
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
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
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(admin_user, slug=slug)
    assert exc_info.value.response.status_code == 409


def test_create_skill_400_on_invalid_bundle_zip(admin_user: DATestUser) -> None:
    corrupt = b"this is not a zip file at all"
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(
            admin_user,
            slug=f"corrupt-{uuid4().hex[:8]}",
            bundle_bytes=corrupt,
        )
    assert exc_info.value.response.status_code == 400


def test_create_skill_413_on_oversized_bundle(admin_user: DATestUser) -> None:
    """An oversized bundle is rejected with 413.

    A single highly-compressible file exceeds the per-file cap but
    compresses to a tiny payload with ZIP_DEFLATED, so the multipart
    upload passes the HTTP parser without issue. The validator's
    streaming size check sees the uncompressed size and raises
    ``PAYLOAD_TOO_LARGE`` (413).
    """
    # CI lowers SKILL_BUNDLE_PER_FILE_MAX_BYTES to 1 MiB; a 2 MiB file trips it.
    oversized_payload = b"A" * (2 * 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: huge\ndescription: huge\n---\nbody\n",
        )
        zf.writestr("big.bin", oversized_payload)
    big_bundle = buf.getvalue()

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
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
    first_row = _fetch_skill_row(first.id)
    assert first_row is not None
    first_blob_id = first_row.bundle_file_id
    assert first_blob_id is not None  # custom skills always have a bundle

    # Snapshot file store blobs before the failing create.
    blobs_before = _skill_bundle_blob_ids()

    # Second create — bundle is fine, but the DB insert fails on the
    # unique-slug check after the blob has already been written. The except
    # branch should delete the just-written blob before re-raising.
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
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
# Sharing
# ---------------------------------------------------------------------------


def test_replace_group_shares_400_on_unknown_group_id(
    admin_user: DATestUser,
) -> None:
    """Unknown group id → 400 with a message that names the failure mode.

    Regression for SHA `c5e427ceab`: FK violations must surface as a 400
    INVALID_INPUT, not a 500.
    """
    skill = SkillManager.create_custom(
        admin_user, slug=f"unknown-grp-{uuid4().hex[:8]}", is_public=False
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.replace_group_shares(skill, [10_000_000], admin_user)

    response = exc_info.value.response
    assert response.status_code == 400
    body = response.json()
    detail = str(body.get("detail") or body)
    assert "group" in detail.lower(), (
        f"error detail must mention groups; got {detail!r}"
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_skill_404_for_nonexistent(admin_user: DATestUser) -> None:
    bogus_id = uuid4()
    response = client.delete(
        f"{API_SERVER_URL}/skills/custom/{bogus_id}",
        headers=admin_user.headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_basic_user_can_create_private_skill(basic_user: DATestUser) -> None:
    skill = SkillManager.create_custom(
        basic_user, slug=f"basic-create-{uuid4().hex[:6]}"
    )
    assert skill.is_public is False
    assert skill.user_permission == "OWNER"


def test_curator_can_post_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Curators can create through the same user-facing endpoint."""
    curator = UserManager.set_role(
        user_to_set=basic_user,
        target_role=UserRole.CURATOR,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    try:
        skill = SkillManager.create_custom(
            curator, slug=f"curator-create-{uuid4().hex[:6]}"
        )
        assert skill.enabled is True
    finally:
        # restore so module-shared basic_user fixture stays BASIC
        UserManager.set_role(
            user_to_set=basic_user,
            target_role=UserRole.BASIC,
            user_performing_action=admin_user,
            explicit_override=True,
        )
