"""Personal (user-level) skill API tests (HTTP boundary).

Covers the user-facing ``POST /skills/custom``,
``PUT /skills/custom/{id}/bundle``, and ``DELETE /skills/custom/{id}``
endpoints: ownership/visibility rules, reserved slugs, duplicate slugs,
promotion to org-wide, and admin disable as a reversible mute.
"""

from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import httpx
import pytest

from onyx.db.enums import SkillSharePermission
from onyx.server.features.skill.models import SkillPatchRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import build_minimal_bundle
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture
def other_basic_user(admin_user: DATestUser) -> DATestUser:  # noqa: ARG001
    # admin_user dependency ensures this user gets the BASIC role
    return UserManager.create(name=f"other_basic_{uuid4().hex[:8]}")


def _user_custom_slugs(user: DATestUser) -> list[str]:
    return [skill.slug for skill in SkillManager.list_for_user(user).customs]


def test_create_personal_skill_visibility(
    admin_user: DATestUser,
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-vis-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)
    assert skill.is_personal is True
    assert skill.public_permission is None

    own_list = SkillManager.list_for_user(basic_user).customs
    mine = [skill for skill in own_list if skill.slug == slug]
    assert len(mine) == 1
    assert mine[0].is_personal is True

    assert slug not in _user_custom_slugs(other_basic_user)

    response = client.get(
        f"{API_SERVER_URL}/skills/{skill.id}",
        headers=other_basic_user.headers,
    )
    assert response.status_code == 404

    admin_customs = SkillManager.list_all(admin_user).customs
    admin_match = [skill for skill in admin_customs if skill.slug == slug]
    assert len(admin_match) == 1
    assert admin_match[0].is_personal is True


def test_create_personal_skill_from_editor(basic_user: DATestUser) -> None:
    suffix = uuid4().hex[:6]
    name = f"editor-skill-{suffix}"

    skill = SkillManager.create_from_editor(
        basic_user,
        name=name,
        description="Created without an uploaded bundle",
        instructions_markdown="# Workflow\n\nFollow these steps.",
        upload_bytes=b"supporting context",
        upload_filename="context.txt",
    )

    editable = SkillManager.get_editable(skill.id, basic_user)
    assert skill.slug == f"editor-skill-{suffix}"
    assert skill.is_personal is True
    assert editable.instructions_markdown == "# Workflow\n\nFollow these steps."
    assert [file.path for file in editable.files] == ["context.txt"]


def test_upload_supporting_files_merges_and_bundle_upload_replaces(
    basic_user: DATestUser,
) -> None:
    original_name = f"original-{uuid4().hex[:6]}"
    skill = SkillManager.create_from_editor(
        basic_user,
        name=original_name,
        description="Original description",
        instructions_markdown="Original instructions.",
    )

    supporting = io.BytesIO()
    with zipfile.ZipFile(supporting, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scripts/run.py", "print('hello')\n")
        zf.writestr("references/context.md", "Context")
    merged = SkillManager.upload_files(
        skill,
        supporting.getvalue(),
        "supporting.zip",
        basic_user,
    )
    assert [file.path for file in merged.files] == [
        "references/context.md",
        "scripts/run.py",
    ]
    assert merged.name == original_name

    after_removal = SkillManager.remove_file(skill, "scripts/run.py", basic_user)
    assert [file.path for file in after_removal.files] == ["references/context.md"]
    assert after_removal.instructions_markdown == "Original instructions."

    replacement = io.BytesIO()
    with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{original_name}/SKILL.md",
            f"---\nname: {original_name}\ndescription: Replaced bundle\n---\n\n"
            "Replacement instructions.",
        )
        zf.writestr(f"{original_name}/new.txt", "new")
    replaced = SkillManager.upload_files(
        skill,
        replacement.getvalue(),
        "replacement.zip",
        basic_user,
    )
    assert replaced.name == original_name
    assert replaced.description == "Replaced bundle"
    assert replaced.instructions_markdown == "Replacement instructions."
    assert [file.path for file in replaced.files] == ["new.txt"]


def test_create_personal_skill_accepts_wrapped_directory(
    basic_user: DATestUser,
) -> None:
    slug = f"personal-wrapped-{uuid4().hex[:6]}"
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{slug}/SKILL.md",
            f"---\nname: {slug}\ndescription: Wrapped directory\n---\n\n"
            "Use the supporting script.",
        )

    skill = SkillManager.create_personal(
        basic_user,
        slug=slug,
        bundle_bytes=bundle.getvalue(),
    )

    assert skill.name == slug
    assert skill.description == "Wrapped directory"


def test_owner_can_fetch_own_personal_skill(basic_user: DATestUser) -> None:
    slug = f"personal-fetch-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    fetched = SkillManager.get_for_user(str(skill.id), basic_user)
    assert fetched.slug == slug
    assert fetched.is_personal is True


def test_owner_can_replace_bundle_and_delete(basic_user: DATestUser) -> None:
    slug = f"personal-mutate-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    new_bundle = build_minimal_bundle(slug, description="Updated personal desc")
    updated = SkillManager.replace_personal_bundle(skill, new_bundle, basic_user)
    assert updated.name == slug
    assert updated.description == "Updated personal desc"
    assert updated.is_personal is True

    SkillManager.delete_personal(skill, basic_user)
    assert slug not in _user_custom_slugs(basic_user)


def test_other_user_cannot_mutate_personal_skill(
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-guard-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    new_bundle = build_minimal_bundle(slug)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.replace_personal_bundle(skill, new_bundle, other_basic_user)
    assert exc_info.value.response.status_code == 404

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.delete_personal(skill, other_basic_user)
    assert exc_info.value.response.status_code == 404

    # still intact for the owner
    assert slug in _user_custom_slugs(basic_user)


def test_create_personal_skill_rejects_reserved_slug(
    basic_user: DATestUser,
) -> None:
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_personal(basic_user, slug="slack")
    response = exc_info.value.response
    assert response.status_code == 400
    body = response.json()
    detail = str(body.get("detail") or body)
    assert "reserved" in detail.lower()


def test_duplicate_slug_across_users_409(
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-dup-{uuid4().hex[:6]}"
    SkillManager.create_personal(basic_user, slug=slug)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_personal(other_basic_user, slug=slug)
    assert exc_info.value.response.status_code == 409


def test_personal_slug_collides_with_admin_skill_both_directions(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    # personal slug shares one namespace with admin/org-wide skills
    admin_slug = f"admin-collide-{uuid4().hex[:6]}"
    SkillManager.create_custom(admin_user, slug=admin_slug, is_public=True)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_personal(basic_user, slug=admin_slug)
    assert exc_info.value.response.status_code == 409

    personal_slug = f"personal-collide-{uuid4().hex[:6]}"
    SkillManager.create_personal(basic_user, slug=personal_slug)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_custom(admin_user, slug=personal_slug, is_public=True)
    assert exc_info.value.response.status_code == 409


def test_admin_can_hard_delete_personal_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Admins can hard-delete any custom skill, mirroring agents/personas."""
    slug = f"personal-admin-delete-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    SkillManager.delete_custom(skill, admin_user)

    assert slug not in _user_custom_slugs(basic_user)
    admin_slugs = [skill.slug for skill in SkillManager.list_all(admin_user).customs]
    assert slug not in admin_slugs


def test_owner_can_share_org_wide_and_retain_edit_permissions(
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-promote-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    promoted = SkillManager.patch_personal(
        skill,
        basic_user,
        SkillPatchRequest(public_permission=SkillSharePermission.VIEWER),
    )
    assert promoted.public_permission is not None
    assert promoted.is_personal is False

    other_list = SkillManager.list_for_user(other_basic_user).customs
    visible = [skill for skill in other_list if skill.slug == slug]
    assert len(visible) == 1
    assert visible[0].is_personal is False

    new_bundle = build_minimal_bundle(slug, description="Owner can still edit")
    updated = SkillManager.replace_personal_bundle(skill, new_bundle, basic_user)
    assert updated.name == slug

    disabled = SkillManager.set_enabled(skill, basic_user, False)
    assert disabled.enabled is False


def test_owner_can_toggle_personal_skill(
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-toggle-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    toggled = SkillManager.set_enabled(skill, basic_user, False)
    assert toggled.enabled is False
    assert toggled.is_personal is True

    # still listed for the owner (greyed out in the UI), enabled=False
    own = [
        skill
        for skill in SkillManager.list_for_user(basic_user).customs
        if skill.slug == slug
    ]
    assert len(own) == 1
    assert own[0].enabled is False

    # still invisible to everyone else
    assert slug not in _user_custom_slugs(other_basic_user)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.set_enabled(skill, other_basic_user, True)
    assert exc_info.value.response.status_code == 404

    reenabled = SkillManager.set_enabled(skill, basic_user, True)
    assert reenabled.enabled is True


def test_user_enablement_is_independent(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """One user's preference does not change another user's preference."""
    slug = f"personal-admin-toggle-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)
    SkillManager.patch_personal(
        skill,
        basic_user,
        SkillPatchRequest(public_permission=SkillSharePermission.VIEWER),
    )

    SkillManager.set_enabled(skill, admin_user, False)
    own = [
        skill
        for skill in SkillManager.list_for_user(basic_user).customs
        if skill.slug == slug
    ]
    assert len(own) == 1 and own[0].enabled is True

    admin_view = SkillManager.get_for_user(skill.id, admin_user)
    assert admin_view.enabled is False
