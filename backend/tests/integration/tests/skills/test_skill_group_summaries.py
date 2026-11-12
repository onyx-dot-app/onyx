"""Group summaries in the Skills list, group settings from the share and bulk
dialogs, the explicit company Available and app skills (G6)."""

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import (
    ExternalAppType,
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import User__UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.server.features.skill.models import (
    SkillEditableDetailResponse,
    SkillGroupSummary,
    SkillResponse,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

_DEFAULT_ACCESS = f"{API_SERVER_URL}/skills/organization-library/default-access"


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(autouse=True)
def _reset_default(admin_user: DATestUser) -> Generator[None, None, None]:
    yield
    _set_default(admin_user, "AVAILABLE").raise_for_status()


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _set_default(admin: DATestUser, policy: str) -> httpx.Response:
    return client.put(
        _DEFAULT_ACCESS, json={"installation_policy": policy}, headers=admin.headers
    )


def _share(user: DATestUser, skill_id: UUID, body: dict[str, Any]) -> SkillResponse:
    response = client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/share",
        json=body,
        headers=user.headers,
    )
    response.raise_for_status()
    return SkillResponse.model_validate(response.json())


def _listed(user: DATestUser) -> dict[UUID, SkillResponse]:
    return {skill.id: skill for skill in SkillManager.list_for_user(user).customs}


def _summaries(
    summaries: list[SkillGroupSummary],
) -> dict[int, tuple[SkillSharePermission | None, PluginInstallationPolicy | None]]:
    return {
        summary.group_id: (summary.permission, summary.installation_policy)
        for summary in summaries
    }


def _promote_to_manager(user_id: str, group_id: int) -> None:
    with get_session_with_current_tenant() as db_session:
        promoted = db_session.scalars(
            update(User__UserGroup)
            .where(
                User__UserGroup.user_id == UUID(user_id),
                User__UserGroup.user_group_id == group_id,
            )
            .values(is_manager=True)
            .returning(User__UserGroup.user_id)
        ).all()
        assert len(promoted) == 1
        recompute_user_permissions__no_commit(UUID(user_id), db_session)
        db_session.commit()


def test_group_summaries_follow_the_share_details_rule(
    admin_user: DATestUser,
) -> None:
    """An editor sees every group row, a scoped manager the rows of their
    groups, and a member none."""
    author = UserManager.create(name=_name("gs_author"))
    member = UserManager.create(name=_name("gs_member"))
    manager = UserManager.create(name=_name("gs_manager"))
    managed = UserGroupManager.create(
        admin_user, name=_name("gs-managed"), user_ids=[member.id, manager.id]
    )
    other = UserGroupManager.create(admin_user, name=_name("gs-other"))
    setting_only = UserGroupManager.create(admin_user, name=_name("gs-setting"))
    _promote_to_manager(manager.id, managed.id)

    skill = SkillManager.create_custom(author)
    saved = _share(
        admin_user,
        skill.id,
        {
            "group_shares": [
                {"group_id": managed.id, "permission": "VIEWER"},
                {"group_id": other.id, "permission": "VIEWER"},
            ],
            "group_settings": [
                {"group_id": managed.id, "installation_policy": "DEFAULT"},
                {"group_id": setting_only.id, "installation_policy": "NOT_AVAILABLE"},
            ],
        },
    )
    expected = {
        managed.id: (SkillSharePermission.VIEWER, PluginInstallationPolicy.DEFAULT),
        other.id: (SkillSharePermission.VIEWER, None),
        setting_only.id: (None, PluginInstallationPolicy.NOT_AVAILABLE),
    }
    assert _summaries(saved.group_summaries) == expected
    # The setting-only row is not a share.
    assert {share.group_id for share in saved.group_shares} == {managed.id, other.id}

    assert _summaries(_listed(author)[skill.id].group_summaries) == expected
    assert _summaries(_listed(admin_user)[skill.id].group_summaries) == expected
    assert _listed(member)[skill.id].group_summaries == []
    manager_view = _listed(manager)[skill.id]
    assert manager_view.user_permission == "VIEWER"
    assert _summaries(manager_view.group_summaries) == {
        managed.id: expected[managed.id]
    }


def test_group_settings_from_the_share_and_bulk_dialogs(
    admin_user: DATestUser,
) -> None:
    """``group_settings`` adds a setting-only row, keeps a share, and null
    removes the setting; a row with no share is then gone."""
    author = UserManager.create(name=_name("gset_author"))
    member = UserManager.create(name=_name("gset_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("gset-group"), user_ids=[member.id]
    )
    first = SkillManager.create_custom(author, is_public=True)
    second = SkillManager.create_custom(author, is_public=True)

    hidden = _share(
        admin_user,
        first.id,
        {
            "group_settings": [
                {"group_id": group.id, "installation_policy": "NOT_AVAILABLE"}
            ]
        },
    )
    assert _summaries(hidden.group_summaries) == {
        group.id: (None, PluginInstallationPolicy.NOT_AVAILABLE)
    }
    # The setting replaces the company setting for the group's members.
    assert first.id not in _listed(member)

    cleared = _share(
        admin_user,
        first.id,
        {"group_settings": [{"group_id": group.id, "installation_policy": None}]},
    )
    assert cleared.group_summaries == []
    assert first.id in _listed(member)

    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        json={
            "action": "share",
            "skill_ids": [str(first.id), str(second.id)],
            "sharing": {
                "group_settings": [
                    {"group_id": group.id, "installation_policy": "REQUIRED"}
                ]
            },
        },
        headers=admin_user.headers,
    )
    response.raise_for_status()
    assert response.json()["failed"] == []
    listed = _listed(member)
    for skill_id in (first.id, second.id):
        assert listed[skill_id].enabled and not listed[skill_id].can_toggle
        assert _summaries(_listed(admin_user)[skill_id].group_summaries) == {
            group.id: (None, PluginInstallationPolicy.REQUIRED)
        }


def test_explicit_available_overrides_a_not_available_default(
    admin_user: DATestUser,
) -> None:
    """AVAILABLE is the skill's own setting; null follows Default Access."""
    author = UserManager.create(name=_name("ea_author"))
    other = UserManager.create(name=_name("ea_other"))
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


def _create_app(admin: DATestUser) -> int:
    app = ExternalAppManager.create(
        user_performing_action=admin,
        name=_name("G6 app"),
        upstream_url_patterns=["https://api.example.com/*"],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={},
        app_type=ExternalAppType.CUSTOM,
    )
    return app.id


def test_app_skills_stay_visible_under_a_not_available_default(
    admin_user: DATestUser,
) -> None:
    """Both app link paths give the skill an explicit Available setting."""
    member = UserManager.create(name=_name("app_member"))
    _set_default(admin_user, "NOT_AVAILABLE").raise_for_status()
    app_id = _create_app(admin_user)
    try:
        linked = SkillManager.create_custom(admin_user)
        client.patch(
            f"{API_SERVER_URL}/build/admin/apps/{app_id}",
            json={"associated_skill_ids": [str(linked.id)]},
            headers=admin_user.headers,
        ).raise_for_status()

        name = _name("app-created")
        created = client.post(
            f"{API_SERVER_URL}/skills/custom/editor",
            data={
                "name": name,
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
