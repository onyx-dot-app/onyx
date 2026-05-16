import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.test_models import DATestUser


def test_non_admin_cannot_create(basic_user: DATestUser) -> None:
    with pytest.raises(requests.HTTPError) as exc_info:
        SkillManager.create_custom(basic_user, slug="unauthorized")
    assert exc_info.value.response.status_code == 403


def test_public_skill_visible_to_all_users(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    SkillManager.create_custom(admin_user, slug="public-skill", is_public=True)

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert "public-skill" in custom_slugs


def test_private_skill_not_visible_without_grant(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    SkillManager.create_custom(admin_user, slug="private-skill", is_public=False)

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert "private-skill" not in custom_slugs


def test_disabled_skill_not_in_user_list(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    skill = SkillManager.create_custom(
        admin_user, slug="disabled-skill", is_public=True
    )
    SkillManager.patch_custom(skill, admin_user, enabled=False)

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert "disabled-skill" not in custom_slugs


def test_disabled_skill_in_admin_list(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, slug="admin-disabled")
    SkillManager.patch_custom(skill, admin_user, enabled=False)

    admin_skills = SkillManager.list_all(admin_user)
    custom_slugs = [c["slug"] for c in admin_skills["customs"]]
    assert "admin-disabled" in custom_slugs


def test_non_admin_cannot_list_admin(basic_user: DATestUser) -> None:
    response = requests.get(
        f"{API_SERVER_URL}/admin/skills",
        headers=basic_user.headers,
    )
    assert response.status_code == 403


def test_non_admin_cannot_delete(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    skill = SkillManager.create_custom(admin_user, slug="no-delete")
    response = requests.delete(
        f"{API_SERVER_URL}/admin/skills/custom/{skill.id}",
        headers=basic_user.headers,
    )
    assert response.status_code == 403
