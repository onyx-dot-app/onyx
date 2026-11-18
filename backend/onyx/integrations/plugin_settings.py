"""The settings of a plugin that holds only integrations: the user's on/off
choice, the install setting, the shares and publishing. A plugin that holds
a skill keeps the skill routes, which also write the legacy skill rows."""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.integration_policy import list_persona_plugin_snapshots
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.plugin import (
    PluginAccessChange,
    PluginGroupGrant,
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
    lock_plugin,
    plugin_holds_only_integrations,
    publish_or_request_review__no_commit,
    set_plugin_preferences__no_commit,
)
from onyx.db.plugin_access import (
    PluginAccess,
    UserPluginState,
    affected_user_ids_for_plugins,
    load_plugin_access,
    load_user_plugin_states,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.policy import agent_plugin_settings
from onyx.server.features.integrations.models import (
    MemberPluginState,
    PluginAccessUpdate,
    PluginAccessView,
    PluginGroupShareView,
    PluginUserShareView,
)


def _not_found() -> OnyxError:
    return OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")


def _user_state(user: User, plugin_id: UUID, db_session: Session) -> UserPluginState:
    states = load_user_plugin_states([user.id], db_session, [plugin_id])
    if not states:
        raise _not_found()
    return states[0]


def _check_holds_only_integrations(plugin_id: UUID, db_session: Session) -> None:
    if not plugin_holds_only_integrations(plugin_id, db_session):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This plugin holds a skill. Change it on the page of its skill.",
        )


def member_plugin_state(
    user: User, plugin_id: UUID, db_session: Session
) -> MemberPluginState:
    state = _user_state(user, plugin_id, db_session)
    return MemberPluginState(
        plugin_id=plugin_id,
        enabled=state.enabled,
        installation_policy=state.installation_policy,
    )


def agent_plugin_ids(user: User, persona_id: int, db_session: Session) -> list[UUID]:
    """The plugins whose integrations a chat of the agent uses for the user,
    the list that chat tool construction reads."""
    try:
        get_persona_by_id(persona_id, user, db_session, is_for_edit=False)
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.PERSONA_NOT_FOUND,
            f"Agent with ID {persona_id} does not exist",
        ) from e
    links = {
        snapshot.plugin_id: snapshot.action_settings
        for snapshot in list_persona_plugin_snapshots(persona_id, db_session)
    }
    return sorted(
        agent_plugin_settings(
            db_session,
            user.id,
            persona_id,
            links,
            published_only=user.is_anonymous,
        ),
        key=str,
    )


def set_plugin_enabled__no_commit(
    user: User, plugin_id: UUID, enabled: bool, db_session: Session
) -> None:
    state = _user_state(user, plugin_id, db_session)
    _check_holds_only_integrations(plugin_id, db_session)
    if not enabled and state.installation_policy == PluginInstallationPolicy.REQUIRED:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Your admin made this plugin Required. You cannot turn it off.",
        )
    set_plugin_preferences__no_commit(user.id, [plugin_id], enabled, db_session)


def _integration_plugin_access(
    user: User, plugin_id: UUID, db_session: Session
) -> PluginAccess:
    access = load_plugin_access([plugin_id], user.id, db_session).get(plugin_id)
    if access is None:
        raise _not_found()
    _check_holds_only_integrations(plugin_id, db_session)
    return access


def set_installation_policy__no_commit(
    user: User,
    plugin_id: UUID,
    policy: PluginInstallationPolicy,
    db_session: Session,
) -> set[UUID]:
    """The caller checked organization-wide manage-actions. Returns the
    affected users."""
    access = _integration_plugin_access(user, plugin_id, db_session)
    if not access.published:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only a plugin in the Organization library has an install setting.",
        )
    result = apply_plugin_access_change__no_commit(
        [plugin_id],
        PluginAccessChange(company_installation_policy=policy),
        None,
        db_session,
    )
    result.raise_first_failure()
    return result.affected_user_ids


def _owned_private_plugin(
    user: User, plugin_id: UUID, db_session: Session, *, token_may_manage: bool
) -> PluginAccess:
    """A private plugin that holds only integrations, which the user owns or
    manages as an organization-wide action manager. ``token_may_manage`` is
    False when the token of the request does not allow Manage actions."""
    access = _integration_plugin_access(user, plugin_id, db_session)
    if access.author_user_id != user.id and not (
        token_may_manage and has_global_permission(user, Permission.MANAGE_ACTIONS)
    ):
        if load_user_plugin_states([user.id], db_session, [plugin_id]):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Only the owner of this plugin can share or publish it.",
            )
        raise _not_found()
    if access.published:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This plugin is in the Organization library. Change its install "
            "setting instead.",
        )
    return access


def plugin_access_view(
    user: User, plugin_id: UUID, db_session: Session, *, token_may_manage: bool
) -> PluginAccessView:
    access = _owned_private_plugin(
        user, plugin_id, db_session, token_may_manage=token_may_manage
    )
    return PluginAccessView(
        plugin_id=plugin_id,
        user_shares=[
            PluginUserShareView(
                user_id=share.user_id, email=share.email, permission=share.permission
            )
            for share in access.user_shares
        ],
        group_shares=[
            PluginGroupShareView(
                group_id=share.group_id,
                group_name=share.group_name,
                permission=share.permission,
            )
            for share in access.group_shares
        ],
    )


def share_plugin__no_commit(
    user: User,
    plugin_id: UUID,
    request: PluginAccessUpdate,
    db_session: Session,
    *,
    token_may_manage: bool,
) -> set[UUID]:
    """Replace the shares. The Sharing setting and the group scope rules of
    skills apply. Returns the affected users."""
    _owned_private_plugin(
        user, plugin_id, db_session, token_may_manage=token_may_manage
    )
    result = apply_plugin_access_change__no_commit(
        [plugin_id],
        PluginAccessChange(
            user_grants=tuple(
                PluginUserGrant(user_id=share.user_id, permission=share.permission)
                for share in request.user_shares
            ),
            group_grants=tuple(
                PluginGroupGrant(group_id=share.group_id, permission=share.permission)
                for share in request.group_shares
            ),
        ),
        user,
        db_session,
    )
    result.raise_first_failure()
    return result.affected_user_ids


def publish_plugin_for_user__no_commit(
    user: User, plugin_id: UUID, db_session: Session, *, token_may_manage: bool
) -> set[UUID]:
    """Move the plugin to the Organization library. Only an
    organization-wide action manager publishes a plugin that holds an
    integration, with no review: there is no review of such a plugin. A used
    name takes the next free name. Returns the affected users."""
    _owned_private_plugin(
        user, plugin_id, db_session, token_may_manage=token_may_manage
    )
    plugin = lock_plugin(plugin_id, db_session)
    if plugin is None:
        raise _not_found()
    before = affected_user_ids_for_plugins([plugin_id], db_session)
    publish_or_request_review__no_commit(
        plugin,
        None,
        plugin.current_version_id,
        None,
        "rename",
        db_session,
        approver=user,
    )
    return before | affected_user_ids_for_plugins([plugin_id], db_session)
