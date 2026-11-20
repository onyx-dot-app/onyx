from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from onyx.db.enums import SkillAccessLevel, SkillSharePermission
from onyx.server.features.skill.models import SkillUserShareRequest
from onyx.server.manage.models import TransferPrivatePluginsResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _delete_user(user: DATestUser, admin: DATestUser) -> httpx.Response:
    return client.request(
        "DELETE",
        f"{API_SERVER_URL}/manage/admin/delete-user",
        json={"user_email": user.email},
        headers=admin.headers,
    )


def _transfer_all(
    user: DATestUser, new_owner: DATestUser, actor: DATestUser
) -> httpx.Response:
    return client.post(
        f"{API_SERVER_URL}/manage/admin/transfer-private-plugins",
        json={"user_email": user.email, "new_owner_user_id": new_owner.id},
        headers=actor.headers,
    )


def test_transfer_all_private_plugins_then_delete(admin_user: DATestUser) -> None:
    owner = UserManager.create(name=f"leaver_{uuid4().hex[:8]}")
    new_owner = UserManager.create(name=f"heir_{uuid4().hex[:8]}")
    sharee = UserManager.create(name=f"sharee_{uuid4().hex[:8]}")
    clash_name = f"clash-{uuid4().hex[:6]}"
    skills = [
        SkillManager.create_custom(owner, name=clash_name),
        SkillManager.create_custom(owner, name=f"keep-a-{uuid4().hex[:6]}"),
        SkillManager.create_custom(owner, name=f"keep-b-{uuid4().hex[:6]}"),
    ]
    SkillManager.create_custom(new_owner, name=clash_name)
    SkillManager.share(
        skills[1],
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(sharee.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )
    owner = UserManager.set_status(owner, False, admin_user)

    refused = _delete_user(owner, admin_user)
    assert refused.status_code == 409
    assert {plugin["id"] for plugin in refused.json()["private_plugins"]} == {
        str(skill.id) for skill in skills
    }

    basic_actor = UserManager.create(name=f"not_admin_{uuid4().hex[:8]}")
    assert _transfer_all(owner, new_owner, basic_actor).status_code == 403

    transferred = _transfer_all(owner, new_owner, admin_user)
    transferred.raise_for_status()
    result = TransferPrivatePluginsResponse.model_validate(transferred.json())
    assert set(result.plugin_ids) == {skill.id for skill in skills}
    assert [(r.plugin_id, r.old_name, r.new_name) for r in result.renames] == [
        (skills[0].id, clash_name, f"{clash_name}-2")
    ]

    _delete_user(owner, admin_user).raise_for_status()

    for skill in skills:
        moved = SkillManager.get_for_user(skill.id, new_owner)
        assert moved.author_user_id == UUID(new_owner.id)
        assert moved.user_permission == SkillAccessLevel.OWNER
        assert moved.published_version_number is None
    assert SkillManager.get_for_user(skills[1].id, sharee).id == skills[1].id


def test_user_with_only_published_plugins_is_deleted(admin_user: DATestUser) -> None:
    owner = UserManager.create(name=f"publisher_{uuid4().hex[:8]}")
    skill = SkillManager.create_custom(owner, name=f"published-{uuid4().hex[:6]}")
    SkillManager.publish(skill.id, admin_user)
    owner = UserManager.set_status(owner, False, admin_user)

    _delete_user(owner, admin_user).raise_for_status()

    assert SkillManager.get_for_user(skill.id, admin_user).author_user_id is None


def test_user_with_no_plugins_is_deleted(admin_user: DATestUser) -> None:
    owner = UserManager.create(name=f"empty_{uuid4().hex[:8]}")
    owner = UserManager.set_status(owner, False, admin_user)

    _delete_user(owner, admin_user).raise_for_status()

    with pytest.raises(httpx.HTTPStatusError):
        UserManager.set_status(owner, True, admin_user)
