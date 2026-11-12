"""The plugins of one group, for the group page. Every write goes through
A1 (``onyx.db.plugin.apply_plugin_access_change__no_commit``)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.models import Plugin, User
from onyx.db.plugin import (
    group_setting_editable_plugin_ids,
    is_plugin_published,
    set_group_install_setting__no_commit,
)
from onyx.db.plugin_access import GroupPluginRow, load_group_plugins
from onyx.db.skill import SkillManagementPolicy, fetch_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


@dataclass(frozen=True)
class UserGroupPluginRow:
    row: GroupPluginRow
    # The caller can change the group's install setting of this plugin.
    can_edit: bool


def list_user_group_plugins(
    group_id: int, actor: User, db_session: Session
) -> list[UserGroupPluginRow]:
    rows = load_group_plugins(group_id, db_session)
    editable = group_setting_editable_plugin_ids(
        [row.plugin_id for row in rows], actor, db_session
    )
    return [
        UserGroupPluginRow(row=row, can_edit=row.plugin_id in editable) for row in rows
    ]


def _check_scoped_manager_can_edit(
    plugin_id: UUID, actor: User, db_session: Session
) -> None:
    """A private plugin must be one the actor can edit."""
    if fetch_skill(
        plugin_id,
        policy=SkillManagementPolicy.EDIT,
        user=actor,
        db_session=db_session,
        lock_for_update=True,
    ):
        return
    plugin = db_session.get(Plugin, plugin_id)
    if plugin is not None and is_plugin_published(plugin, db_session):
        return
    if (
        fetch_skill(
            plugin_id,
            policy=SkillManagementPolicy.VIEW,
            user=actor,
            db_session=db_session,
        )
        is None
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "Only an organization-wide skill manager, or a group manager who can "
        "edit this skill, can change its group install settings.",
    )


def set_user_group_plugin_setting__no_commit(
    group_id: int,
    plugin_id: UUID,
    policy: PluginInstallationPolicy | None,
    actor: User,
    db_session: Session,
) -> set[UUID]:
    """Set or remove the group's install setting of a plugin, or add a
    private plugin to the group as a VIEWER share. A user without
    organization-wide MANAGE_PLUGINS must be able to edit a private plugin.
    Returns the affected users. A1 refuses a scoped manager on a published
    plugin."""
    if not has_global_permission(actor, Permission.MANAGE_PLUGINS):
        _check_scoped_manager_can_edit(plugin_id, actor, db_session)
    return set_group_install_setting__no_commit(
        plugin_id, group_id, policy, actor, db_session
    ).affected_user_ids
