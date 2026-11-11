"""Every access write to a custom skill also goes to its plugin, and the legacy
skill rows stay correct. Publishing is one-way, and the organization never
gets edit access.

The API has no plugin reads yet, so these tests read the plugin rows from the
database after each request."""

import datetime
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import SkillSharePermission
from onyx.db.models import (
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
    UserPluginPreference,
)
from onyx.server.features.skill.models import (
    SkillGroupShareRequest,
    SkillResponse,
    SkillUserShareRequest,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import (
    SkillManager,
    build_minimal_bundle,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.utils.plugin_access import (
    ORGANIZATION_LIBRARY_ID,
    plugin_access_mismatches,
    user_uploads_id,
)


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def owner() -> DATestUser:
    return UserManager.create(name=f"plugin_access_{uuid4().hex[:8]}")


def _user(prefix: str) -> DATestUser:
    return UserManager.create(name=f"{prefix}_{uuid4().hex[:8]}")


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


# --- Requests ----------------------------------------------------------------


def _share(user: DATestUser, skill_id: UUID | str, body: dict[str, Any]) -> Any:
    return client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/share",
        json=body,
        headers=user.headers,
    )


def _patch(user: DATestUser, skill_id: UUID | str, body: dict[str, Any]) -> Any:
    return client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}",
        json=body,
        headers=user.headers,
    )


def _bulk(user: DATestUser, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"{API_SERVER_URL}/skills/bulk", json=body, headers=user.headers
    )
    response.raise_for_status()
    return response.json()


def _transfer(user: DATestUser, skill_id: UUID | str, new_owner_id: str) -> Any:
    return client.post(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/transfer-ownership",
        json={"new_owner_user_id": new_owner_id},
        headers=user.headers,
    )


def _delete(user: DATestUser, skill_id: UUID | str) -> Any:
    return client.delete(
        f"{API_SERVER_URL}/skills/custom/{skill_id}", headers=user.headers
    )


def _publish(user: DATestUser, skill: SkillResponse) -> SkillResponse:
    return SkillManager.share(skill, user, is_public=True)


# --- Database reads ----------------------------------------------------------


def _assert_rows_match(*skill_ids: UUID | str) -> None:
    with get_session_with_current_tenant() as db_session:
        assert plugin_access_mismatches(db_session, skill_ids) == []


def _plugin(skill_id: UUID | str) -> Plugin:
    with get_session_with_current_tenant() as db_session:
        plugin = db_session.get(Plugin, UUID(str(skill_id)))
        assert plugin is not None
        db_session.expunge(plugin)
        return plugin


def _plugin_or_none(skill_id: UUID | str) -> Plugin | None:
    with get_session_with_current_tenant() as db_session:
        return db_session.get(Plugin, UUID(str(skill_id)))


def _user_share_created_at(
    skill_id: UUID | str, user_id: str
) -> datetime.datetime | None:
    with get_session_with_current_tenant() as db_session:
        return db_session.scalar(
            select(Plugin__User.created_at).where(
                Plugin__User.plugin_id == UUID(str(skill_id)),
                Plugin__User.user_id == UUID(user_id),
            )
        )


def _group_share_created_at(
    skill_id: UUID | str, group_id: int
) -> datetime.datetime | None:
    with get_session_with_current_tenant() as db_session:
        return db_session.scalar(
            select(Plugin__UserGroup.created_at).where(
                Plugin__UserGroup.plugin_id == UUID(str(skill_id)),
                Plugin__UserGroup.user_group_id == group_id,
            )
        )


def _choice(
    skill_id: UUID | str, user_id: str
) -> tuple[bool, datetime.datetime | None] | None:
    with get_session_with_current_tenant() as db_session:
        row = db_session.execute(
            select(UserPluginPreference.enabled, UserPluginPreference.enabled_at).where(
                UserPluginPreference.plugin_id == UUID(str(skill_id)),
                UserPluginPreference.user_id == UUID(user_id),
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None


def _drop_plugin(skill_id: UUID | str) -> None:
    """Leave the skill with no plugin row, as an older server does."""
    with get_session_with_current_tenant() as db_session:
        plugin = db_session.get(Plugin, UUID(str(skill_id)))
        assert plugin is not None
        db_session.delete(plugin)
        db_session.commit()


# --- Shares ------------------------------------------------------------------


def test_share_writes_plugin_shares(admin_user: DATestUser) -> None:
    # Group shares need group-manager rights, so the admin owns the skill.
    owner = admin_user
    viewer = _user("share_viewer")
    editor = _user("share_editor")
    group = UserGroupManager.create(admin_user, name=_name("share-group"))
    skill = SkillManager.create_custom(owner, name=_name("share"))

    SkillManager.share(
        skill,
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id), permission=SkillSharePermission.VIEWER
            ),
            SkillUserShareRequest(
                user_id=UUID(editor.id), permission=SkillSharePermission.EDITOR
            ),
        ],
        group_shares=[
            SkillGroupShareRequest(
                group_id=group.id, permission=SkillSharePermission.VIEWER
            )
        ],
    )
    _assert_rows_match(skill.id)
    viewer_created_at = _user_share_created_at(skill.id, viewer.id)
    assert viewer_created_at is not None
    assert _group_share_created_at(skill.id, group.id) is not None

    # A changed level keeps the share's created_at; a removed share goes.
    SkillManager.share(
        skill,
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id), permission=SkillSharePermission.EDITOR
            )
        ],
        group_shares=[],
    )
    _assert_rows_match(skill.id)
    assert _user_share_created_at(skill.id, viewer.id) == viewer_created_at
    assert _user_share_created_at(skill.id, editor.id) is None
    assert _group_share_created_at(skill.id, group.id) is None


def test_bulk_share_writes_plugin_rows(admin_user: DATestUser) -> None:
    owner = admin_user
    other = _user("bulk_other")
    viewer = _user("bulk_viewer")
    group = UserGroupManager.create(admin_user, name=_name("bulk-group"))
    first = SkillManager.create_custom(owner, name=_name("bulk-a"))
    second = SkillManager.create_custom(owner, name=_name("bulk-b"))
    SkillManager.share(
        first,
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(other.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )

    result = _bulk(
        owner,
        {
            "action": "share",
            "skill_ids": [str(first.id), str(second.id)],
            "sharing": {
                "public_permission": "VIEWER",
                "user_shares": [{"user_id": viewer.id, "permission": "EDITOR"}],
                "group_shares": [{"group_id": group.id, "permission": "VIEWER"}],
            },
        },
    )
    assert result["failed"] == []
    _assert_rows_match(first.id, second.id)
    for skill in (first, second):
        plugin = _plugin(skill.id)
        assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
        assert plugin.published_version_id == plugin.current_version_id
    # Bulk adds to the shares a skill has.
    assert _user_share_created_at(first.id, other.id) is not None


# --- Publishing --------------------------------------------------------------


def test_publish_moves_plugin_to_organization_library(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner, name=_name("publish"))
    before = _plugin(skill.id)
    assert before.marketplace_id == user_uploads_id(owner.id)
    assert before.published_version_id is None

    published = _publish(owner, skill)
    assert published.public_permission == SkillSharePermission.VIEWER
    after = _plugin(skill.id)
    assert after.marketplace_id == ORGANIZATION_LIBRARY_ID
    assert after.published_version_id == after.current_version_id
    assert after.name == skill.name
    assert after.author_user_id == UUID(owner.id)
    _assert_rows_match(skill.id)

    # Publishing a published plugin changes nothing.
    _publish(owner, skill)
    again = _plugin(skill.id)
    assert (again.marketplace_id, again.name, again.published_version_id) == (
        after.marketplace_id,
        after.name,
        after.published_version_id,
    )


def test_publish_with_a_used_name_returns_conflict(owner: DATestUser) -> None:
    other = _user("publish_other")
    name = _name("same")
    first = SkillManager.create_custom(other, name=name, auto_enable=False)
    _publish(other, first)
    second = SkillManager.create_custom(owner, name=name, auto_enable=False)

    response = _share(owner, second.id, {"public_permission": "VIEWER"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONFLICT"
    assert name in response.json()["detail"]
    assert SkillManager.get_for_user(str(second.id), owner).public_permission is None
    assert _plugin(second.id).marketplace_id == user_uploads_id(owner.id)
    _assert_rows_match(first.id, second.id)


def test_create_public_with_a_used_name_takes_a_free_name(owner: DATestUser) -> None:
    other = _user("create_public_other")
    name = _name("created-public")
    first = SkillManager.create_custom(other, name=name, auto_enable=False)
    _publish(other, first)

    headers = dict(owner.headers)
    headers.pop("Content-Type", None)
    response = client.post(
        f"{API_SERVER_URL}/skills/custom/batch",
        headers=headers,
        files=[
            ("bundles", (f"{name}.zip", build_minimal_bundle(name), "application/zip"))
        ],
        data={"sharing": '{"public_permission":"VIEWER"}'},
    )
    response.raise_for_status()
    result = response.json()
    assert result["not_imported"] == []
    [item] = result["imported"]
    assert item["skill"]["name"] == name
    assert item["skill"]["public_permission"] == "VIEWER"

    plugin = _plugin(item["skill"]["id"])
    assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
    assert plugin.name == f"{name}-2"
    assert plugin.published_version_id == plugin.current_version_id
    _assert_rows_match(first.id, item["skill"]["id"])


def test_published_skill_cannot_be_made_private(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner, name=_name("one-way"))
    _publish(owner, skill)

    share = _share(owner, skill.id, {"public_permission": None})
    assert share.status_code == 400
    assert "cannot be made private" in share.json()["detail"]
    patch = _patch(owner, skill.id, {"public_permission": None})
    assert patch.status_code == 400
    bulk = _bulk(
        owner,
        {
            "action": "share",
            "skill_ids": [str(skill.id)],
            "sharing": {"public_permission": None},
        },
    )
    assert bulk["succeeded"] == []
    assert "cannot be made private" in bulk["failed"][0]["detail"]

    assert (
        SkillManager.get_for_user(str(skill.id), owner).public_permission
        == SkillSharePermission.VIEWER
    )
    assert _plugin(skill.id).marketplace_id == ORGANIZATION_LIBRARY_ID
    _assert_rows_match(skill.id)


def test_organization_editor_is_refused(owner: DATestUser) -> None:
    private = SkillManager.create_custom(owner, name=_name("org-edit-a"))
    published = SkillManager.create_custom(owner, name=_name("org-edit-b"))
    _publish(owner, published)

    for skill in (private, published):
        response = _share(owner, skill.id, {"public_permission": "EDITOR"})
        assert response.status_code == 400
        assert "edit access" in response.json()["detail"]
        assert _patch(owner, skill.id, {"public_permission": "EDITOR"}).status_code == (
            400
        )
    bulk = _bulk(
        owner,
        {
            "action": "share",
            "skill_ids": [str(private.id), str(published.id)],
            "sharing": {"public_permission": "EDITOR"},
        },
    )
    assert bulk["succeeded"] == []
    assert len(bulk["failed"]) == 2
    assert all("edit access" in failure["detail"] for failure in bulk["failed"])

    assert SkillManager.get_for_user(str(private.id), owner).public_permission is None
    assert (
        SkillManager.get_for_user(str(published.id), owner).public_permission
        == SkillSharePermission.VIEWER
    )
    _assert_rows_match(private.id, published.id)


# --- Install setting ---------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "plugin_policy"),
    [("DEFAULT", "DEFAULT"), ("REQUIRED", "REQUIRED"), ("AVAILABLE", None)],
)
def test_install_setting_writes_plugin_policy(
    admin_user: DATestUser, policy: str, plugin_policy: str | None
) -> None:
    single = SkillManager.create_custom(admin_user, name=_name("policy"))
    bulk = SkillManager.create_custom(admin_user, name=_name("policy-bulk"))
    if policy == "AVAILABLE":
        for skill in (single, bulk):
            _share(
                admin_user, skill.id, {"installation_policy": "DEFAULT"}
            ).raise_for_status()

    _share(admin_user, single.id, {"installation_policy": policy}).raise_for_status()
    result = _bulk(
        admin_user,
        {
            "action": "share",
            "skill_ids": [str(bulk.id)],
            "sharing": {"installation_policy": policy},
        },
    )
    assert result["failed"] == []

    for skill in (single, bulk):
        policy_value = _plugin(skill.id).installation_policy
        assert (policy_value.value if policy_value else None) == plugin_policy
    _assert_rows_match(single.id, bulk.id)


# --- User choices ------------------------------------------------------------


def test_enable_and_disable_write_the_user_choice(owner: DATestUser) -> None:
    skill = SkillManager.create_custom(owner, name=_name("choice"))
    # The auto-enable on create writes the choice with enabled_at.
    created = _choice(skill.id, owner.id)
    assert created is not None and created[0] is True and created[1] is not None
    _assert_rows_match(skill.id)

    SkillManager.set_enabled(skill, owner, enabled=False)
    disabled = _choice(skill.id, owner.id)
    assert disabled == (False, created[1])
    _assert_rows_match(skill.id)

    SkillManager.set_enabled(skill, owner, enabled=True)
    enabled = _choice(skill.id, owner.id)
    assert enabled is not None and enabled[0] is True
    assert enabled[1] is not None and enabled[1] > created[1]
    _assert_rows_match(skill.id)

    result = _bulk(owner, {"action": "disable", "skill_ids": [str(skill.id)]})
    assert result["failed"] == []
    assert _choice(skill.id, owner.id) == (False, enabled[1])
    result = _bulk(owner, {"action": "enable", "skill_ids": [str(skill.id)]})
    assert result["failed"] == []
    bulk_enabled = _choice(skill.id, owner.id)
    assert bulk_enabled is not None and bulk_enabled[0] is True
    assert bulk_enabled[1] is not None and bulk_enabled[1] > enabled[1]
    _assert_rows_match(skill.id)


def test_replacing_a_same_named_skill_turns_the_other_plugin_off(
    owner: DATestUser,
) -> None:
    name = _name("same-choice")
    first = SkillManager.create_custom(owner, name=name)
    second = SkillManager.create_custom(owner, name=name, auto_enable=False)

    SkillManager.set_enabled(second, owner, enabled=True, replace_conflict=True)
    first_choice = _choice(first.id, owner.id)
    second_choice = _choice(second.id, owner.id)
    assert first_choice is not None and first_choice[0] is False
    assert second_choice is not None and second_choice[0] is True
    _assert_rows_match(first.id, second.id)


# --- Transfer ----------------------------------------------------------------


def test_transfer_moves_private_plugin_to_new_owner(owner: DATestUser) -> None:
    new_owner = _user("transfer_new")
    skill = SkillManager.create_custom(owner, name=_name("transfer"))
    SkillManager.share(
        skill,
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(new_owner.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )

    _transfer(owner, skill.id, new_owner.id).raise_for_status()
    plugin = _plugin(skill.id)
    assert plugin.author_user_id == UUID(new_owner.id)
    assert plugin.marketplace_id == user_uploads_id(new_owner.id)
    assert plugin.name == skill.name
    # The new owner's share goes; the previous owner keeps EDITOR.
    assert _user_share_created_at(skill.id, new_owner.id) is None
    assert _user_share_created_at(skill.id, owner.id) is not None
    _assert_rows_match(skill.id)


def test_transfer_with_a_used_name_returns_conflict(owner: DATestUser) -> None:
    new_owner = _user("transfer_clash")
    name = _name("transfer-clash")
    SkillManager.create_custom(new_owner, name=name)
    skill = SkillManager.create_custom(owner, name=name)

    response = _transfer(owner, skill.id, new_owner.id)
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONFLICT"
    assert name in response.json()["detail"]
    assert SkillManager.get_for_user(str(skill.id), owner).owner is not None
    plugin = _plugin(skill.id)
    assert plugin.author_user_id == UUID(owner.id)
    assert plugin.marketplace_id == user_uploads_id(owner.id)
    _assert_rows_match(skill.id)


def test_transfer_keeps_a_published_plugin_published(owner: DATestUser) -> None:
    new_owner = _user("transfer_published")
    skill = SkillManager.create_custom(owner, name=_name("transfer-pub"))
    _publish(owner, skill)

    _transfer(owner, skill.id, new_owner.id).raise_for_status()
    plugin = _plugin(skill.id)
    assert plugin.author_user_id == UUID(new_owner.id)
    assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
    _assert_rows_match(skill.id)


# --- Delete ------------------------------------------------------------------


def test_only_a_manager_can_delete_a_published_skill(
    owner: DATestUser, admin_user: DATestUser
) -> None:
    single = SkillManager.create_custom(owner, name=_name("delete-pub"))
    bulk = SkillManager.create_custom(owner, name=_name("delete-pub-bulk"))
    private = SkillManager.create_custom(owner, name=_name("delete-private"))
    _publish(owner, single)
    _publish(owner, bulk)

    response = _delete(owner, single.id)
    assert response.status_code == 403
    assert "Only an admin" in response.json()["detail"]
    result = _bulk(owner, {"action": "delete", "skill_ids": [str(bulk.id)]})
    assert result["succeeded"] == []
    assert "Only an admin" in result["failed"][0]["detail"]
    assert _plugin_or_none(single.id) is not None
    assert _plugin_or_none(bulk.id) is not None

    # The owner still deletes a private skill.
    _delete(owner, private.id).raise_for_status()
    assert _plugin_or_none(private.id) is None

    _delete(admin_user, single.id).raise_for_status()
    result = _bulk(admin_user, {"action": "delete", "skill_ids": [str(bulk.id)]})
    assert result["succeeded"] == [str(bulk.id)]
    assert _plugin_or_none(single.id) is None
    assert _plugin_or_none(bulk.id) is None


# --- Skills with no plugin row -----------------------------------------------


@pytest.mark.parametrize("change", ["share", "publish", "policy", "enable", "transfer"])
def test_access_write_on_skill_without_plugin_row_converges(
    owner: DATestUser, admin_user: DATestUser, change: str
) -> None:
    viewer = _user("converge_viewer")
    skill = SkillManager.create_custom(owner, name=_name("converge"))
    SkillManager.share(
        skill,
        owner,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(viewer.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )
    _drop_plugin(skill.id)

    if change == "share":
        response = _share(
            owner,
            skill.id,
            {"group_shares": []},
        )
    elif change == "publish":
        response = _share(owner, skill.id, {"public_permission": "VIEWER"})
    elif change == "policy":
        response = _share(admin_user, skill.id, {"installation_policy": "DEFAULT"})
    elif change == "enable":
        response = client.put(
            f"{API_SERVER_URL}/skills/{skill.id}/enabled",
            json={"enabled": False},
            headers=owner.headers,
        )
    else:
        response = _transfer(owner, skill.id, viewer.id)
    response.raise_for_status()

    # The plugin is made from the legacy rows, with the shares and choices
    # that were there before, and then gets the change.
    assert _plugin_or_none(skill.id) is not None
    _assert_rows_match(skill.id)
