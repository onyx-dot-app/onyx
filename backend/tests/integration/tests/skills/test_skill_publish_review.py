"""Publish, publish update and admin review under the Publishing setting."""

import json
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest

from onyx.db.enums import (
    PluginPublishingPolicy,
    PluginReviewStatus,
    SkillSharePermission,
)
from onyx.db.plugin import BUNDLES_KEPT
from onyx.server.features.skill.models import (
    SkillBulkResponse,
    SkillPatchRequest,
    SkillResponse,
    SkillUserShareRequest,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

_OFF_DETAIL = (
    "Publishing to the organization is turned off. Ask an admin to publish this skill."
)


def _set_publishing(admin: DATestUser, policy: PluginPublishingPolicy) -> None:
    response = client.patch(
        f"{API_SERVER_URL}/admin/settings",
        json={"plugin_publishing": policy.value},
        headers=admin.headers,
    )
    response.raise_for_status()
    assert response.json()["plugin_publishing"] == policy.value


@pytest.fixture(autouse=True)
def _open_publishing_after(admin_user: DATestUser) -> Generator[None, None, None]:
    yield
    _set_publishing(admin_user, PluginPublishingPolicy.OPEN)


@pytest.fixture
def owner() -> DATestUser:
    return UserManager.create(name=f"publish_owner_{uuid4().hex[:8]}")


def _statuses(skill_id: UUID, user: DATestUser) -> dict[int, PluginReviewStatus]:
    return {
        version.version_number: version.review_status
        for version in SkillManager.list_all_versions(skill_id, user)
    }


def _save(skill: SkillResponse, user: DATestUser, description: str) -> None:
    SkillManager.patch_custom(skill, user, SkillPatchRequest(description=description))


def _version_id(skill_id: UUID, number: int, user: DATestUser) -> UUID:
    for version in SkillManager.list_all_versions(skill_id, user):
        if version.version_number == number:
            return version.id
    raise AssertionError(f"version {number} not found")


def _published_with_newer_draft(owner: DATestUser, admin: DATestUser) -> SkillResponse:
    """A published skill whose organization runs version 1 while the owner
    has version 2. Leaves the Publishing setting at REQUIRES_REVIEW."""
    _set_publishing(admin, PluginPublishingPolicy.OPEN)
    skill = SkillManager.create_custom(owner, description="Version one")
    SkillManager.publish(skill.id, owner)
    _save(skill, owner, "Version two")
    _set_publishing(admin, PluginPublishingPolicy.REQUIRES_REVIEW)
    skill = SkillManager.get_for_user(skill.id, owner)
    assert skill.public_permission == SkillSharePermission.VIEWER
    assert (skill.published_version_number, skill.current_version_number) == (1, 2)
    return skill


def _assert_refused_off(response: Any) -> None:
    assert response.status_code == 403
    assert response.json()["detail"] == _OFF_DETAIL


def test_off_refuses_every_publish_path(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    published = _published_with_newer_draft(owner, admin_user)
    _set_publishing(admin_user, PluginPublishingPolicy.OFF)
    skill = SkillManager.create_custom(owner)

    _assert_refused_off(SkillManager.publish_response(skill.id, owner))
    _assert_refused_off(SkillManager.publish_response(published.id, owner))
    _assert_refused_off(
        client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
            json={"public_permission": "VIEWER"},
            headers=owner.headers,
        )
    )
    _assert_refused_off(
        client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            json={"public_permission": "VIEWER"},
            headers=owner.headers,
        )
    )
    headers = dict(owner.headers)
    headers.pop("Content-Type", None)
    _assert_refused_off(
        client.post(
            f"{API_SERVER_URL}/skills/custom/editor",
            files={
                "name": (None, f"off-{uuid4().hex[:8]}", None),
                "description": (None, "Refused", None),
                "instructions_markdown": (None, "Refused.", None),
                "sharing": (None, json.dumps({"public_permission": "VIEWER"}), None),
            },
            headers=headers,
        )
    )
    bulk = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        json={
            "skill_ids": [str(skill.id)],
            "action": "share",
            "sharing": {"public_permission": "VIEWER"},
        },
        headers=owner.headers,
    )
    bulk.raise_for_status()
    assert [
        failure.detail
        for failure in SkillBulkResponse.model_validate(bulk.json()).failed
    ] == [_OFF_DETAIL]

    assert SkillManager.get_for_user(skill.id, owner).public_permission is None
    assert SkillManager.get_for_user(published.id, owner).published_version_number == 1


def test_open_publishes_at_once(owner: DATestUser, admin_user: DATestUser) -> None:
    published = _published_with_newer_draft(owner, admin_user)
    _set_publishing(admin_user, PluginPublishingPolicy.OPEN)
    skill = SkillManager.create_custom(owner)

    first = SkillManager.publish(skill.id, owner)
    update = SkillManager.publish(published.id, owner)

    assert first.public_permission == SkillSharePermission.VIEWER
    assert first.published_version_number == 1
    assert _statuses(skill.id, owner) == {1: PluginReviewStatus.PUBLISHED}
    assert update.published_version_number == 2
    assert _statuses(published.id, owner) == {
        2: PluginReviewStatus.PUBLISHED,
        1: PluginReviewStatus.SUPERSEDED,
    }


def test_only_the_author_publishes_an_update(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    published = _published_with_newer_draft(owner, admin_user)
    editor = UserManager.create(name=f"publish_editor_{uuid4().hex[:8]}")
    SkillManager.share(
        published,
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(editor.id), permission=SkillSharePermission.EDITOR
            )
        ],
    )
    _set_publishing(admin_user, PluginPublishingPolicy.OPEN)

    refused = SkillManager.publish_response(published.id, editor, None)
    assert refused.status_code == 403

    stale = SkillManager.publish_response(
        published.id, owner, _version_id(published.id, 1, owner)
    )
    assert stale.status_code == 409

    assert SkillManager.publish(published.id, owner).published_version_number == 2


def test_requires_review_makes_a_pending_request(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    _set_publishing(admin_user, PluginPublishingPolicy.REQUIRES_REVIEW)
    by_route = SkillManager.create_custom(owner)
    by_share = SkillManager.create_custom(owner)
    published = _published_with_newer_draft(owner, admin_user)

    first = SkillManager.publish(by_route.id, owner)
    shared = client.patch(
        f"{API_SERVER_URL}/skills/custom/{by_share.id}/share",
        json={"public_permission": "VIEWER"},
        headers=owner.headers,
    )
    shared.raise_for_status()
    update = SkillManager.publish(published.id, owner)

    for response in (first, SkillResponse.model_validate(shared.json())):
        assert response.public_permission is None
        assert response.is_personal
        assert response.published_version_number is None
        assert response.pending_version_number == 1
    assert update.published_version_number == 1
    assert update.pending_version_number == 2
    assert _statuses(published.id, owner) == {
        2: PluginReviewStatus.PENDING,
        1: PluginReviewStatus.PUBLISHED,
    }
    requests = {
        request.skill_id: request
        for request in SkillManager.list_review_requests(admin_user)
    }
    assert requests[by_route.id].version_number == 1
    assert requests[by_route.id].published_version_number is None
    assert requests[by_route.id].requested_by_email == owner.email
    assert requests[by_share.id].version_number == 1
    assert requests[published.id].version_number == 2
    assert requests[published.id].published_version_number == 1


@pytest.mark.parametrize("policy", list(PluginPublishingPolicy))
def test_organization_manager_publishes_at_once(
    owner: DATestUser, admin_user: DATestUser, policy: PluginPublishingPolicy
) -> None:
    published = _published_with_newer_draft(owner, admin_user)
    _set_publishing(admin_user, policy)
    skill = SkillManager.create_custom(admin_user)

    assert SkillManager.publish(skill.id, admin_user).published_version_number == 1
    assert SkillManager.publish(published.id, admin_user).published_version_number == 2
    assert (
        SkillManager.get_for_user(skill.id, admin_user).pending_version_number is None
    )


def test_approve_publishes_the_pending_version(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    published = _published_with_newer_draft(owner, admin_user)
    assert _statuses(published.id, owner) == {
        2: PluginReviewStatus.DRAFT,
        1: PluginReviewStatus.PUBLISHED,
    }
    viewer = UserManager.create(name=f"publish_viewer_{uuid4().hex[:8]}")
    assert SkillManager.preview(published.id, viewer).description == "Version one"

    SkillManager.publish(published.id, owner)
    pending = _version_id(published.id, 2, owner)
    refused = SkillManager.review_response(published.id, pending, "approve", owner)
    assert refused.status_code == 403
    approved = SkillManager.review(published.id, pending, "approve", admin_user)

    assert approved.published_version_number == 2
    assert approved.pending_version_number is None
    assert _statuses(published.id, owner) == {
        2: PluginReviewStatus.PUBLISHED,
        1: PluginReviewStatus.SUPERSEDED,
    }
    assert SkillManager.preview(published.id, viewer).description == "Version two"
    assert published.id not in {
        request.skill_id for request in SkillManager.list_review_requests(admin_user)
    }


def test_deny_keeps_the_skill_private(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    _set_publishing(admin_user, PluginPublishingPolicy.REQUIRES_REVIEW)
    skill = SkillManager.create_custom(owner)
    SkillManager.publish(skill.id, owner)
    version_id = _version_id(skill.id, 1, owner)

    denied = SkillManager.review(skill.id, version_id, "deny", admin_user)

    assert denied.public_permission is None
    assert denied.pending_version_number is None
    assert _statuses(skill.id, owner) == {1: PluginReviewStatus.DENIED}
    again = SkillManager.review_response(skill.id, version_id, "approve", admin_user)
    assert again.status_code == 409
    assert skill.id not in {
        request.skill_id for request in SkillManager.list_review_requests(admin_user)
    }


def test_newer_request_supersedes_the_pending_one(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    _set_publishing(admin_user, PluginPublishingPolicy.REQUIRES_REVIEW)
    skill = SkillManager.create_custom(owner)
    SkillManager.publish(skill.id, owner)
    _save(skill, owner, "Second")

    second = SkillManager.publish(skill.id, owner)

    assert second.pending_version_number == 2
    assert _statuses(skill.id, owner) == {
        2: PluginReviewStatus.PENDING,
        1: PluginReviewStatus.SUPERSEDED,
    }
    assert [
        request.version_number
        for request in SkillManager.list_review_requests(admin_user)
        if request.skill_id == skill.id
    ] == [2]
    old = SkillManager.review_response(
        skill.id, _version_id(skill.id, 1, owner), "approve", admin_user
    )
    assert old.status_code == 409


def test_approve_refuses_a_version_not_newer_than_the_published_one(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    published = _published_with_newer_draft(owner, admin_user)
    SkillManager.publish(published.id, owner)
    _save(published, owner, "Version three")
    SkillManager.publish(published.id, admin_user)
    assert SkillManager.get_for_user(published.id, owner).published_version_number == 3

    response = SkillManager.review_response(
        published.id, _version_id(published.id, 2, owner), "approve", admin_user
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Only a version newer than the published version can be approved."
    )


def _bundle_kept(skill_id: UUID, user: DATestUser) -> dict[int, bool]:
    return {
        version.version_number: version.bundle_kept
        for version in SkillManager.list_all_versions(skill_id, user)
    }


def test_retention_keeps_the_pending_version(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    _set_publishing(admin_user, PluginPublishingPolicy.REQUIRES_REVIEW)
    skill = SkillManager.create_custom(owner)
    SkillManager.publish(skill.id, owner)
    for number in range(2, BUNDLES_KEPT + 2):
        _save(skill, owner, f"Version {number}")

    kept = _bundle_kept(skill.id, owner)

    assert len(kept) == BUNDLES_KEPT + 1
    assert all(kept.values())
    assert _statuses(skill.id, owner)[1] == PluginReviewStatus.PENDING


def test_retention_prunes_denied_bundles_first(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    _set_publishing(admin_user, PluginPublishingPolicy.REQUIRES_REVIEW)
    skill = SkillManager.create_custom(owner)
    _save(skill, owner, "Version 2")
    SkillManager.publish(skill.id, owner)
    SkillManager.review(skill.id, _version_id(skill.id, 2, owner), "deny", admin_user)
    for number in range(3, BUNDLES_KEPT + 2):
        _save(skill, owner, f"Version {number}")

    kept = _bundle_kept(skill.id, owner)

    assert len(kept) == BUNDLES_KEPT + 1
    assert not kept[2]
    assert all(kept[number] for number in kept if number != 2)
    preview = SkillManager.preview_version(
        skill.id, _version_id(skill.id, 2, owner), owner
    )
    assert preview.description == "Version 2"
