from __future__ import annotations

import io
import zipfile
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.auth.schemas import UserRole
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import SkillPatchRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import (
    SkillManager,
    build_minimal_bundle,
)
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


def _mark_skill_invalid(skill_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        skill = db_session.get(Skill, skill_id)
        assert skill is not None
        skill.is_valid = False
        db_session.commit()


def _bundle_blob_exists(bundle_file_id: str) -> bool:
    return get_default_file_store().has_file(
        file_id=bundle_file_id,
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )


# ---------------------------------------------------------------------------
# Existing tests preserved
# ---------------------------------------------------------------------------


def test_create_and_list_skill(admin_user: DATestUser) -> None:
    name = f"test-create-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(admin_user, name=name)
    assert skill.name == name
    assert skill.enabled is True

    skills_list = SkillManager.list_all(admin_user)
    [listed_skill] = [
        candidate for candidate in skills_list.customs if candidate.id == skill.id
    ]
    assert listed_skill.name == name
    assert listed_skill.enabled is True


def test_patch_skill_metadata(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, name=f"patch-test-{uuid4().hex[:6]}")

    public = SkillManager.patch_custom(
        skill,
        admin_user,
        SkillPatchRequest(public_permission=SkillSharePermission.VIEWER),
    )
    assert public.public_permission == SkillSharePermission.VIEWER


def test_invalid_skill_is_manageable_but_not_toggleable(
    admin_user: DATestUser,
) -> None:
    skill = SkillManager.create_custom(
        admin_user,
        name=f"invalid-toggle-{uuid4().hex[:6]}",
    )
    _mark_skill_invalid(skill.id)

    listed = SkillManager.list_all(admin_user)
    [invalid_skill] = [row for row in listed.customs if row.id == skill.id]
    assert invalid_skill.is_valid is False
    assert invalid_skill.can_toggle is False

    response = client.put(
        f"{API_SERVER_URL}/skills/{skill.id}/enabled",
        json={"enabled": False},
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_replace_bundle_updates_metadata(admin_user: DATestUser) -> None:
    name = f"bundle-test-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(
        admin_user,
        name=name,
        description="Original desc",
    )
    new_bundle = build_minimal_bundle(name, description="Updated desc")
    updated = SkillManager.replace_bundle(skill, new_bundle, admin_user)
    assert updated.name == name
    assert updated.description == "Updated desc"


def test_delete_skill(admin_user: DATestUser) -> None:
    name = f"delete-test-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(admin_user, name=name)
    SkillManager.delete_custom(skill, admin_user)

    skills_list = SkillManager.list_all(admin_user)
    custom_names = [skill.name for skill in skills_list.customs]
    assert name not in custom_names


def test_bundle_missing_skill_md(admin_user: DATestUser) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no skill.md here")
    bad_bundle = buf.getvalue()

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(
            admin_user, name=f"bad-bundle-{uuid4().hex[:6]}", bundle_bytes=bad_bundle
        )
    assert exc_info.value.response.status_code == 400


def test_group_shares_replace(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(
        admin_user, name=f"group-shares-test-{uuid4().hex[:6]}", is_public=False
    )
    updated = SkillManager.replace_group_shares(skill, [], admin_user)
    assert updated.group_shares == []


def test_metadata_from_bundle_frontmatter(admin_user: DATestUser) -> None:
    bundle = build_minimal_bundle("from-frontmatter", description="From bundle desc")
    skill = SkillManager.create_custom(
        admin_user, name="from-frontmatter", bundle_bytes=bundle
    )
    assert skill.name == "from-frontmatter"
    assert skill.description == "From bundle desc"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_skill_201_persists_row_group_shares_bundle(
    admin_user: DATestUser,
) -> None:
    """POST -> row persisted with bundle blob and group shares visible in DB."""
    group = UserGroupManager.create(admin_user, name="create-shares-group")

    name = f"persist-{uuid4().hex[:8]}"
    skill = SkillManager.create_custom(
        admin_user,
        name=name,
        is_public=False,
        group_ids=[group.id],
    )

    assert [share.group_id for share in skill.group_shares] == [group.id]

    row = _fetch_skill_row(skill.id)
    assert row is not None, "skill row missing after create"
    assert row.name == name
    assert row.public_permission is None
    assert row.bundle_file_id, "skill row has no bundle_file_id"
    assert _bundle_blob_exists(row.bundle_file_id), (
        f"bundle blob {row.bundle_file_id} not present in file store after create"
    )


def test_create_skill_rejects_reserved_name(admin_user: DATestUser) -> None:
    reserved = "company-search"
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(admin_user, name=reserved)
    response = exc_info.value.response
    assert response.status_code == 400
    body = response.json()
    detail = str(body.get("detail") or body)
    assert reserved in detail, (
        f"error message must name the reserved name; got {detail!r}"
    )


def test_create_skill_allows_disabled_duplicate_name(admin_user: DATestUser) -> None:
    name = f"duplicate-{uuid4().hex[:8]}"

    first = SkillManager.create_custom(admin_user, name=name)
    second = SkillManager.create_custom(admin_user, name=name, auto_enable=False)

    assert first.id != second.id
    assert first.enabled is True
    assert second.enabled is False
    matching = [
        skill
        for skill in SkillManager.list_all(admin_user).customs
        if skill.name == name
    ]
    assert {skill.id for skill in matching} == {first.id, second.id}


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
            name=f"too-big-{uuid4().hex[:8]}",
            bundle_bytes=big_bundle,
        )
    assert exc_info.value.response.status_code == 413


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
        admin_user, name=f"unknown-grp-{uuid4().hex[:8]}", is_public=False
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
        basic_user, name=f"basic-create-{uuid4().hex[:6]}"
    )
    assert skill.public_permission is None
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
            curator, name=f"curator-create-{uuid4().hex[:6]}"
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
