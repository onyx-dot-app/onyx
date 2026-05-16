import io
import zipfile

import pytest
import requests

from tests.integration.common_utils.managers.skill import build_minimal_bundle
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.test_models import DATestUser


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
