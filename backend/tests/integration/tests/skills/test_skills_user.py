"""User skill API tests (HTTP boundary).

These tests live at the user-facing HTTP boundary for ``/skills`` and
``/skills/{slug_or_id}``. They verify visibility rules (public, private,
grants, disabled), the slug + id lookup contract, and the admin-only
delete guard.

Admin-route auth (POST, list, etc.) is covered exhaustively in
``test_skills_admin.py``; here we only assert the user-side surface.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def test_get_skills_returns_builtins_plus_accessible_customs(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """The user listing returns both built-ins and visible customs."""
    SkillManager.create_custom(
        admin_user, slug=f"mixed-public-{uuid4().hex[:6]}", is_public=True
    )

    user_skills = SkillManager.list_for_user(basic_user)
    # Built-ins ship with the deployment; the registry always returns at
    # least one entry for an out-of-the-box install.
    assert isinstance(user_skills.get("builtins"), list)
    assert isinstance(user_skills.get("customs"), list)
    assert len(user_skills["builtins"]) >= 1
    assert len(user_skills["customs"]) >= 1


def test_user_does_not_see_disabled_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    slug = f"disabled-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(admin_user, slug=slug, is_public=True)
    SkillManager.patch_custom(skill, admin_user, enabled=False)

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert slug not in custom_slugs


def test_user_does_not_see_private_skill_without_grant(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    slug = f"private-nogrant-{uuid4().hex[:6]}"
    SkillManager.create_custom(admin_user, slug=slug, is_public=False)

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert slug not in custom_slugs


def test_user_sees_public_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    slug = f"public-{uuid4().hex[:6]}"
    SkillManager.create_custom(admin_user, slug=slug, is_public=True)

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert slug in custom_slugs


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User-group management requires EE features enabled.",
)
def test_user_sees_private_skill_with_grant(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Adding ``basic_user`` to a granted group surfaces a private skill."""
    group = UserGroupManager.create(
        admin_user,
        name=f"grant-r-{uuid4().hex[:6]}",
        user_ids=[admin_user.id],
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[group],
    )
    UserGroupManager.add_users(group, [basic_user.id], admin_user)

    slug = f"private-granted-{uuid4().hex[:6]}"
    SkillManager.create_custom(
        admin_user,
        slug=slug,
        is_public=False,
        group_ids=[group.id],
    )

    user_skills = SkillManager.list_for_user(basic_user)
    custom_slugs = [c["slug"] for c in user_skills["customs"]]
    assert slug in custom_slugs


def test_get_skill_by_slug_404_when_not_visible(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """A private skill the user has no grant for → 404 on direct slug lookup."""
    slug = f"hidden-slug-{uuid4().hex[:6]}"
    SkillManager.create_custom(admin_user, slug=slug, is_public=False)

    response = client.get(
        f"{API_SERVER_URL}/skills/{slug}",
        headers=basic_user.headers,
    )
    assert response.status_code == 404


def test_get_skill_by_id_404_when_not_visible(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Direct lookup by UUID obeys the same visibility filter as listing."""
    slug = f"hidden-id-{uuid4().hex[:6]}"
    skill = SkillManager.create_custom(admin_user, slug=slug, is_public=False)
    assert skill.id is not None

    response = client.get(
        f"{API_SERVER_URL}/skills/{skill.id}",
        headers=basic_user.headers,
    )
    assert response.status_code == 404


def test_non_admin_cannot_delete_skill(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Regular users get 403 when deleting via the admin route."""
    skill = SkillManager.create_custom(admin_user, slug=f"no-del-{uuid4().hex[:6]}")
    response = client.delete(
        f"{API_SERVER_URL}/admin/skills/custom/{skill.id}",
        headers=basic_user.headers,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Notes on coverage shifted to ``test_skills_admin.py``
# ---------------------------------------------------------------------------
# - ``test_non_admin_cannot_create`` → covered by
#   ``test_skills_admin.py::test_non_admin_returns_403_on_post``.
# - ``test_disabled_skill_in_admin_list`` → admin-side behaviour, covered
#   by the admin patch/list flow in ``test_skills_admin.py``.
# - ``test_non_admin_cannot_list_admin`` → covered by
#   ``test_skills_admin.py::test_non_admin_returns_403_on_admin_list``.
