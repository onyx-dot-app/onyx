"""Install setting writes through the skills API (G3): the Organization
library default, Not available, group settings, the Sharing setting, the
response fields and name clashes."""

from collections.abc import Generator

import httpx
import pytest

from onyx.db.enums import PluginInstallationPolicy
from onyx.server.features.skill.models import SkillResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.skills.conftest import (
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
    assert share_skill(admin_user, setting_first.id, share).status_code == 400
    [row] = SkillManager.get_for_user(setting_first.id, admin_user).group_summaries
    assert (row.permission, row.installation_policy) == (
        None,
        PluginInstallationPolicy.NOT_AVAILABLE,
    )


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


def test_hidden_enabled_row_does_not_block_a_toggle() -> None:
    """A user who turned on a shared skill and lost the share can turn on
    their own skill with the same name."""
    user = UserManager.create(name=unique_name("hidden_user"))
    owner = UserManager.create(name=unique_name("hidden_owner"))
    name = unique_name("hidden")
    shared = SkillManager.create_custom(owner, name=name)
    share_skill(
        owner,
        shared.id,
        {"user_shares": [{"user_id": user.id, "permission": "VIEWER"}]},
    ).raise_for_status()
    SkillManager.set_enabled(shared, user, True)
    share_skill(owner, shared.id, {"user_shares": []}).raise_for_status()

    own = SkillManager.create_custom(user, name=name, auto_enable=False)
    turned_on = SkillManager.set_enabled(own, user, True)
    assert turned_on.enabled


def test_transfer_with_a_name_clash_returns_conflict() -> None:
    owner = UserManager.create(name=unique_name("transfer_owner"))
    target = UserManager.create(name=unique_name("transfer_target"))
    name = unique_name("clash")
    SkillManager.create_custom(target, name=name)
    skill = SkillManager.create_custom(owner, name=name)

    response = client.post(
        f"{API_SERVER_URL}/skills/custom/{skill.id}/transfer-ownership",
        json={"new_owner_user_id": target.id},
        headers=owner.headers,
    )
    assert response.status_code == 409
    assert "already has a skill named" in response.json()["detail"]
