"""Install setting writes through the skills API (G3): the Organization
library default, Not available, group settings, the Sharing setting, the
response fields and name clashes."""

from collections.abc import Generator
from typing import Any
from uuid import UUID

import httpx
import pytest

from onyx.db.enums import ExternalAppType, PluginInstallationPolicy
from onyx.server.features.skill.models import (
    SkillEditableDetailResponse,
    SkillResponse,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.skills.conftest import (
    promote_to_manager,
    share_skill,
    unique_name,
    visible_skill_ids,
)

_DEFAULT_ACCESS = f"{API_SERVER_URL}/skills/organization-library/default-access"


def _set_default(admin: DATestUser, policy: str) -> httpx.Response:
    return client.put(
        _DEFAULT_ACCESS, json={"installation_policy": policy}, headers=admin.headers
    )


def _set_sharing(admin: DATestUser, enabled: bool) -> None:
    client.patch(
        f"{API_SERVER_URL}/admin/settings",
        json={"plugin_sharing": enabled},
        headers=admin.headers,
    ).raise_for_status()


@pytest.fixture(autouse=True)
def _reset_settings(admin_user: DATestUser) -> Generator[None, None, None]:
    yield
    _set_default(admin_user, "AVAILABLE").raise_for_status()
    _set_sharing(admin_user, True)


def test_organization_library_default_not_available(
    admin_user: DATestUser,
) -> None:
    """A newly published skill reaches only its author and direct shares until
    an admin gives it a company or group setting."""
    author = UserManager.create(name=unique_name("default_author"))
    shared = UserManager.create(name=unique_name("default_shared"))
    group_member = UserManager.create(name=unique_name("default_member"))
    other = UserManager.create(name=unique_name("default_other"))
    group = UserGroupManager.create(
        admin_user, name=unique_name("default-group"), user_ids=[group_member.id]
    )

    assert _set_default(admin_user, "REQUIRED").status_code == 400
    response = _set_default(admin_user, "NOT_AVAILABLE")
    response.raise_for_status()
    assert (
        client.get(_DEFAULT_ACCESS, headers=admin_user.headers).json()[
            "installation_policy"
        ]
        == "NOT_AVAILABLE"
    )

    skill = SkillManager.create_custom(author, name=unique_name("default-skill"))
    share_skill(
        author,
        skill.id,
        {
            "public_permission": "VIEWER",
            "user_shares": [{"user_id": shared.id, "permission": "VIEWER"}],
        },
    ).raise_for_status()

    assert skill.id in visible_skill_ids(author)
    assert skill.id in visible_skill_ids(shared)
    assert skill.id not in visible_skill_ids(group_member)
    assert skill.id not in visible_skill_ids(other)
    shown = SkillManager.get_for_user(skill.id, shared)
    assert shown.installation_policy is None
    assert shown.default_installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
    # The share gives Available: off until the user turns it on.
    assert not shown.enabled and shown.can_toggle

    # A group setting reaches the group's members only.
    share_skill(
        admin_user,
        skill.id,
        {
            "group_shares": [{"group_id": group.id, "permission": "VIEWER"}],
            "group_settings": [
                {"group_id": group.id, "installation_policy": "DEFAULT"}
            ],
        },
    ).raise_for_status()
    assert skill.id in visible_skill_ids(group_member)
    assert skill.id not in visible_skill_ids(other)
    member_view = SkillManager.get_for_user(skill.id, group_member)
    # Installed by default: on, and the member can turn it off.
    assert member_view.enabled and member_view.can_toggle

    # A company setting reaches everyone.
    share_skill(
        admin_user, skill.id, {"installation_policy": "DEFAULT"}
    ).raise_for_status()
    assert skill.id in visible_skill_ids(other)


def test_not_available_company_setting(admin_user: DATestUser) -> None:
    author = UserManager.create(name=unique_name("na_author"))
    other = UserManager.create(name=unique_name("na_other"))
    skill = SkillManager.create_custom(author, is_public=True)
    assert skill.id in visible_skill_ids(other)

    response = share_skill(
        admin_user, skill.id, {"installation_policy": "NOT_AVAILABLE"}
    )
    response.raise_for_status()
    shown = SkillResponse.model_validate(response.json())
    assert shown.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
    assert skill.id not in visible_skill_ids(other)
    # The author still sees it and can turn it on.
    assert skill.id in visible_skill_ids(author)
    assert SkillManager.get_for_user(skill.id, author).can_toggle


def test_shared_group_with_not_available_is_refused(admin_user: DATestUser) -> None:
    """A group with a share cannot be Not available, with the setting set
    before or after the share."""
    group = UserGroupManager.create(admin_user, name=unique_name("na-shared"))
    share = {"group_shares": [{"group_id": group.id, "permission": "VIEWER"}]}
    not_available = {
        "group_settings": [
            {"group_id": group.id, "installation_policy": "NOT_AVAILABLE"}
        ]
    }
    shared = SkillManager.create_custom(admin_user, name=unique_name("na-shared"))
    share_skill(admin_user, shared.id, share).raise_for_status()
    response = share_skill(admin_user, shared.id, not_available)
    assert response.status_code == 400
    assert "Remove the group's share first" in response.json()["detail"]

    setting_first = SkillManager.create_custom(admin_user, is_public=True)
    share_skill(admin_user, setting_first.id, not_available).raise_for_status()
    response = share_skill(admin_user, setting_first.id, share)
    assert response.status_code == 400
    assert "Ask a skill manager" in response.json()["detail"]


def test_member_share_is_refused_while_sharing_is_off(
    admin_user: DATestUser,
) -> None:
    owner = UserManager.create(name=unique_name("sharing_owner"))
    viewer = UserManager.create(name=unique_name("sharing_viewer"))
    skill = SkillManager.create_custom(owner)
    body = {"user_shares": [{"user_id": viewer.id, "permission": "VIEWER"}]}

    _set_sharing(admin_user, False)
    response = share_skill(owner, skill.id, body)
    assert response.status_code == 403
    assert "Sharing with people and groups is turned off" in response.json()["detail"]
    share_skill(admin_user, skill.id, body).raise_for_status()
    assert skill.id in visible_skill_ids(viewer)


def _listed(user: DATestUser) -> dict[UUID, SkillResponse]:
    return {skill.id: skill for skill in SkillManager.list_for_user(user).customs}


def _share(user: DATestUser, skill_id: UUID, body: dict[str, Any]) -> SkillResponse:
    response = share_skill(user, skill_id, body)
    response.raise_for_status()
    return SkillResponse.model_validate(response.json())


def test_explicit_available_overrides_a_not_available_default(
    admin_user: DATestUser,
) -> None:
    """AVAILABLE is the skill's own setting; null follows Default access."""
    author = UserManager.create(name=unique_name("ea_author"))
    other = UserManager.create(name=unique_name("ea_other"))
    _set_default(admin_user, "NOT_AVAILABLE").raise_for_status()
    skill = SkillManager.create_custom(author, is_public=True)

    shown = _listed(admin_user)[skill.id]
    assert shown.installation_policy is None
    assert shown.default_installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
    assert skill.id not in _listed(other)

    explicit = _share(admin_user, skill.id, {"installation_policy": "AVAILABLE"})
    assert explicit.installation_policy == PluginInstallationPolicy.AVAILABLE
    other_view = _listed(other)[skill.id]
    assert not other_view.enabled and other_view.can_toggle
    assert other_view.installation_policy == PluginInstallationPolicy.AVAILABLE

    # A save that leaves the setting out keeps it.
    kept = _share(admin_user, skill.id, {"user_shares": []})
    assert kept.installation_policy == PluginInstallationPolicy.AVAILABLE
    assert skill.id in _listed(other)

    inherited = _share(admin_user, skill.id, {"installation_policy": None})
    assert inherited.installation_policy is None
    assert skill.id not in _listed(other)


def test_app_skills_stay_visible_under_a_not_available_default(
    admin_user: DATestUser,
) -> None:
    """Both app link paths give the skill an explicit Available setting."""
    member = UserManager.create(name=unique_name("app_member"))
    _set_default(admin_user, "NOT_AVAILABLE").raise_for_status()
    app_id = ExternalAppManager.create(
        user_performing_action=admin_user,
        name=unique_name("default app"),
        upstream_url_patterns=["https://api.example.com/*"],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={},
        app_type=ExternalAppType.CUSTOM,
    ).id
    try:
        linked = SkillManager.create_custom(admin_user)
        client.patch(
            f"{API_SERVER_URL}/build/admin/apps/{app_id}",
            json={"associated_skill_ids": [str(linked.id)]},
            headers=admin_user.headers,
        ).raise_for_status()

        created = client.post(
            f"{API_SERVER_URL}/skills/custom/editor",
            data={
                "name": unique_name("app-created"),
                "description": "An app skill.",
                "instructions_markdown": "Use the app.",
                "external_app_id": str(app_id),
            },
            headers={
                key: value
                for key, value in admin_user.headers.items()
                if key.lower() != "content-type"
            },
        )
        created.raise_for_status()
        created_id = SkillEditableDetailResponse.model_validate(created.json()).id

        listed = _listed(member)
        for skill_id in (linked.id, created_id):
            assert skill_id in listed
            assert listed[skill_id].installation_policy == (
                PluginInstallationPolicy.AVAILABLE
            )
    finally:
        ExternalAppManager.delete(admin_user, app_id)


def test_group_required_skill_permissions_through_the_api(
    admin_user: DATestUser,
) -> None:
    """A group Required setting: a member cannot turn the skill off, and only
    an organization-wide skill manager deletes it, not its owner, who manages
    the group."""
    member = UserManager.create(name=unique_name("req_member"))
    manager = UserManager.create(name=unique_name("req_manager"))
    group = UserGroupManager.create(
        admin_user, name=unique_name("req-group"), user_ids=[member.id, manager.id]
    )
    promote_to_manager(manager.id, group.id)
    skill = SkillManager.create_custom(manager, group_ids=[group.id])
    share_skill(
        admin_user,
        skill.id,
        {"group_settings": [{"group_id": group.id, "installation_policy": "REQUIRED"}]},
    ).raise_for_status()

    member_view = SkillManager.get_for_user(skill.id, member)
    assert member_view.enabled and not member_view.can_toggle
    turned_off = client.put(
        f"{API_SERVER_URL}/skills/{skill.id}/enabled",
        json={"enabled": False},
        headers=member.headers,
    )
    assert turned_off.status_code == 400
    assert SkillManager.get_for_user(skill.id, member).enabled

    assert not SkillManager.get_for_user(skill.id, manager).can_delete
    refused = client.delete(
        f"{API_SERVER_URL}/skills/custom/{skill.id}", headers=manager.headers
    )
    assert refused.status_code == 403
    assert SkillManager.get_for_user(skill.id, admin_user).can_delete
    client.delete(
        f"{API_SERVER_URL}/skills/custom/{skill.id}", headers=admin_user.headers
    ).raise_for_status()


def test_transfer_is_refused_while_sharing_is_off(admin_user: DATestUser) -> None:
    """A transfer keeps the old owner as an editor, which is a share."""
    owner = UserManager.create(name=unique_name("transfer_off_owner"))
    target = UserManager.create(name=unique_name("transfer_off_target"))
    skill = SkillManager.create_custom(owner)
    body = {"new_owner_user_id": target.id}
    url = f"{API_SERVER_URL}/skills/custom/{skill.id}/transfer-ownership"

    _set_sharing(admin_user, False)
    refused = client.post(url, json=body, headers=owner.headers)
    assert refused.status_code == 403
    assert "Sharing with people and groups is turned off" in refused.json()["detail"]
    _set_sharing(admin_user, True)
    client.post(url, json=body, headers=owner.headers).raise_for_status()
