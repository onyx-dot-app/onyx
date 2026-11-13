"""The run-time skill limit (G7b) through the API: a group join that puts a
user past 500 MB, and the admin list of users past it.

Sizes are written to plugin_version rows, so small real bundles stand for
large ones."""

from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Plugin, PluginVersion, User
from onyx.skills.limits import (
    SKILL_RUNTIME_MAX_BYTES,
    SKILL_WRITE_MAX_BYTES,
    SKILL_WRITE_MAX_FILES,
)
from onyx.skills.push import build_user_skills_payload
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.skills.conftest import unique_name

_RESIZED: list[UUID] = []


@pytest.fixture(autouse=True)
def _reset_sizes() -> Generator[None, None, None]:
    yield
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(PluginVersion)
            .where(PluginVersion.plugin_id.in_(_RESIZED))
            .values(file_manifest=None, unpacked_size_bytes=0, file_count=0)
        )
        db_session.commit()
    _RESIZED.clear()


def _set_size(skill_id: UUID | str, size: int) -> None:
    plugin_id = UUID(str(skill_id))
    with get_session_with_current_tenant() as db_session:
        current = select(Plugin.current_version_id).where(Plugin.id == plugin_id)
        db_session.execute(
            update(PluginVersion)
            .where(PluginVersion.id == current.scalar_subquery())
            .values(
                file_manifest=[{"path": "data", "size": size, "sha256": "0" * 64}],
                unpacked_size_bytes=size,
                file_count=1,
            )
        )
        db_session.commit()
    _RESIZED.append(plugin_id)


def _over_limit(admin: DATestUser) -> dict[str, dict[str, Any]]:
    response = client.get(
        f"{API_SERVER_URL}/skills/users-over-limit", headers=admin.headers
    )
    response.raise_for_status()
    body = response.json()
    assert body["max_bytes"] == SKILL_WRITE_MAX_BYTES
    assert body["max_files"] == SKILL_WRITE_MAX_FILES
    return {user["user_id"]: user for user in body["users"]}


def test_group_join_past_500_mb_keeps_every_skill_under_900_mb(
    admin_user: DATestUser,
) -> None:
    author = UserManager.create(name=unique_name("rt_author"))
    member = UserManager.create(name=unique_name("rt_member"))
    group = UserGroupManager.create(admin_user, name=unique_name("rt-group"))
    names = [unique_name("rt-skill") for _ in range(3)]
    for name in names:
        skill = SkillManager.create_custom(author, name=name, auto_enable=False)
        _set_size(skill.id, SKILL_RUNTIME_MAX_BYTES * 3 // 10)
        # The group is empty, so the write check passes.
        client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
            json={
                "group_shares": [{"group_id": group.id, "permission": "VIEWER"}],
                "group_settings": [
                    {"group_id": group.id, "installation_policy": "DEFAULT"}
                ],
            },
            headers=admin_user.headers,
        ).raise_for_status()
    assert member.id not in _over_limit(admin_user)

    # A membership change is never refused.
    UserGroupManager.wait_for_sync(admin_user, [group])
    UserGroupManager.add_users(group, [member.id], admin_user)

    listed = _over_limit(admin_user)[member.id]
    assert listed["usage"]["bytes"] > SKILL_WRITE_MAX_BYTES
    assert listed["skills_not_loaded"] == 0
    with get_session_with_current_tenant() as db_session:
        user = db_session.get(User, UUID(member.id))
        assert user is not None
        payload = build_user_skills_payload(user, db_session)
    assert payload.omissions == ()
    for name in names:
        assert f"{name}/SKILL.md" in payload.files

    # Only admins who manage plugins read the list.
    response = client.get(
        f"{API_SERVER_URL}/skills/users-over-limit", headers=member.headers
    )
    assert response.status_code == 403
