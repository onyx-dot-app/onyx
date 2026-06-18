"""Personal (user-level) skill API tests (HTTP boundary).

Covers the user-facing ``POST /skills/custom``,
``PUT /skills/custom/{id}/bundle``, and ``DELETE /skills/custom/{id}``
endpoints: ownership/visibility rules, reserved slugs, duplicate slugs,
promotion to org-wide, admin disable as a reversible mute, and the
per-user cap.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from onyx.server.features.skill.api import MAX_PERSONAL_SKILLS_PER_USER
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
    return [c["slug"] for c in SkillManager.list_for_user(user)["customs"]]


def test_create_personal_skill_visibility(
    admin_user: DATestUser,
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-vis-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)
    assert skill.is_personal is True
    assert skill.is_public is False

    own_list = SkillManager.list_for_user(basic_user)["customs"]
    mine = [c for c in own_list if c["slug"] == slug]
    assert len(mine) == 1
    assert mine[0]["is_personal"] is True

    assert slug not in _user_custom_slugs(other_basic_user)

    response = client.get(
        f"{API_SERVER_URL}/skills/{slug}",
        headers=other_basic_user.headers,
    )
    assert response.status_code == 404

    response = client.get(
        f"{API_SERVER_URL}/skills/{skill.id}",
        headers=other_basic_user.headers,
    )
    assert response.status_code == 404

    admin_customs = SkillManager.list_all(admin_user)["customs"]
    admin_match = [c for c in admin_customs if c["slug"] == slug]
    assert len(admin_match) == 1
    assert admin_match[0]["is_personal"] is True


def test_owner_can_fetch_own_personal_skill(basic_user: DATestUser) -> None:
    slug = f"personal-fetch-{uuid4().hex[:6]}"
    SkillManager.create_personal(basic_user, slug=slug)

    fetched = SkillManager.get_for_user(slug, basic_user)
    assert fetched["slug"] == slug
    assert fetched["is_personal"] is True


def test_owner_can_replace_bundle_and_delete(basic_user: DATestUser) -> None:
    slug = f"personal-mutate-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    new_bundle = build_minimal_bundle(
        slug, name="Renamed Personal", description="Updated personal desc"
    )
    updated = SkillManager.replace_personal_bundle(skill, new_bundle, basic_user)
    assert updated.name == "Renamed Personal"
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
    slug = f"personal-admin-kill-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    # admin's hard kill switch (the admin DELETE route) wipes another user's
    # personal skill outright
    SkillManager.delete_custom(skill, admin_user)

    assert slug not in _user_custom_slugs(basic_user)
    admin_slugs = [c["slug"] for c in SkillManager.list_all(admin_user)["customs"]]
    assert slug not in admin_slugs


def test_promotion_makes_skill_org_wide_and_locks_owner_out(
    admin_user: DATestUser,
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-promote-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    promoted = SkillManager.patch_custom(skill, admin_user, is_public=True)
    assert promoted.is_public is True
    assert promoted.is_personal is False

    other_list = SkillManager.list_for_user(other_basic_user)["customs"]
    visible = [c for c in other_list if c["slug"] == slug]
    assert len(visible) == 1
    assert visible[0]["is_personal"] is False

    new_bundle = build_minimal_bundle(slug)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.replace_personal_bundle(skill, new_bundle, basic_user)
    assert exc_info.value.response.status_code == 403

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.delete_personal(skill, basic_user)
    assert exc_info.value.response.status_code == 403


def test_owner_can_toggle_personal_skill(
    basic_user: DATestUser,
    other_basic_user: DATestUser,
) -> None:
    slug = f"personal-toggle-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    toggled = SkillManager.patch_personal(skill, basic_user, enabled=False)
    assert toggled.enabled is False
    assert toggled.is_personal is True

    # still listed for the owner (greyed out in the UI), enabled=False
    own = [
        c
        for c in SkillManager.list_for_user(basic_user)["customs"]
        if c["slug"] == slug
    ]
    assert len(own) == 1
    assert own[0]["enabled"] is False

    # still invisible to everyone else
    assert slug not in _user_custom_slugs(other_basic_user)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.patch_personal(skill, other_basic_user, enabled=True)
    assert exc_info.value.response.status_code == 404

    reenabled = SkillManager.patch_personal(skill, basic_user, enabled=True)
    assert reenabled.enabled is True


def test_owner_cannot_toggle_after_promotion(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    slug = f"personal-toggle-promo-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)
    SkillManager.patch_custom(skill, admin_user, is_public=True)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.patch_personal(skill, basic_user, enabled=False)
    assert exc_info.value.response.status_code == 403


def test_admin_disable_then_owner_reenable(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Admin disable is a reversible mute, not a sticky lock: the skill stays
    listed (greyed) for the owner and the owner can re-enable it. The admin's
    irreversible override is delete (see test_admin_can_hard_delete_personal_skill)."""
    slug = f"personal-admin-toggle-{uuid4().hex[:6]}"
    skill = SkillManager.create_personal(basic_user, slug=slug)

    SkillManager.patch_custom(skill, admin_user, enabled=False)
    own = [
        c
        for c in SkillManager.list_for_user(basic_user)["customs"]
        if c["slug"] == slug
    ]
    assert len(own) == 1 and own[0]["enabled"] is False

    # enabled is a shared flag with no who-disabled tracking, so the owner can
    # turn it back on.
    reenabled = SkillManager.patch_personal(skill, basic_user, enabled=True)
    assert reenabled.enabled is True


def test_per_user_personal_skill_cap(admin_user: DATestUser) -> None:  # noqa: ARG001
    # dedicated user so personal skills from other tests don't skew the count
    capped_user = UserManager.create(name=f"capped_{uuid4().hex[:8]}")
    for i in range(MAX_PERSONAL_SKILLS_PER_USER):
        SkillManager.create_personal(capped_user, slug=f"cap-{i}-{uuid4().hex[:6]}")

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        SkillManager.create_personal(capped_user, slug=f"cap-over-{uuid4().hex[:6]}")
    response = exc_info.value.response
    assert response.status_code == 400
    body = response.json()
    detail = str(body.get("detail") or body)
    assert "limit" in detail.lower()
