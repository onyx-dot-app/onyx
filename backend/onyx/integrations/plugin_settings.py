"""The access settings of an integration, for the routes that name it by the
plugin that holds it: the user's on/off choice, the install setting, the
shares and publishing. Each read and write is on the integration. The plugin
id is only its handle. A plugin that holds a skill keeps the skill routes."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.integration import lock_integration
from onyx.db.integration_access import (
    UserIntegrationState,
    affected_user_ids_for_integrations,
    load_integration_shares,
    load_user_integration_states,
    replace_integration_shares__no_commit,
    set_integration_preferences__no_commit,
)
from onyx.db.integration_policy import (
    get_plugin_names,
    list_persona_plugin_snapshots,
    list_plugin_integrations,
)
from onyx.db.models import Integration, User
from onyx.db.persona import get_persona_by_id
from onyx.db.plugin import plugin_holds_only_integrations
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations import policy
from onyx.server.features.integrations.models import (
    MemberPluginState,
    PluginAccessUpdate,
    PluginAccessView,
    PluginGroupShareView,
    PluginUserShareView,
)


def _not_found() -> OnyxError:
    return OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")


def _single_integration(
    plugin_id: UUID, held: list[tuple[UUID, Integration]], db_session: Session
) -> Integration:
    """The integration that the plugin id names: the one integration of a
    plugin that holds no skill."""
    if not held:
        raise _not_found()
    if not plugin_holds_only_integrations(plugin_id, db_session):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This plugin holds a skill. Change it on the page of its skill.",
        )
    if len(held) > 1:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This plugin holds more than one integration.",
        )
    return held[0][1]


def _integration_of_plugin(
    plugin_id: UUID, db_session: Session, *, lock: bool
) -> Integration:
    integration = _single_integration(
        plugin_id, list_plugin_integrations(db_session, [plugin_id]), db_session
    )
    if lock and lock_integration(integration.id, db_session) is None:
        raise _not_found()
    return integration


def _user_state(
    user: User, integration: Integration, db_session: Session
) -> UserIntegrationState | None:
    states = load_user_integration_states([user.id], db_session, [integration.id])
    return states[0] if states else None


def _accessible_integration(
    user: User, plugin_id: UUID, db_session: Session
) -> tuple[Integration, UserIntegrationState]:
    """The integration of the plugin with its state for the user. NOT_FOUND
    when the user has no access, whatever the plugin holds."""
    held = list_plugin_integrations(db_session, [plugin_id])
    states = load_user_integration_states(
        [user.id], db_session, [integration.id for _, integration in held]
    )
    if not states:
        raise _not_found()
    return _single_integration(plugin_id, held, db_session), states[0]


def member_plugin_state(
    user: User, plugin_id: UUID, db_session: Session
) -> MemberPluginState:
    _, state = _accessible_integration(user, plugin_id, db_session)
    return MemberPluginState(
        plugin_id=plugin_id,
        enabled=state.turned_on,
        installation_policy=state.installation_policy,
    )


def agent_plugin_ids(user: User, persona_id: int, db_session: Session) -> list[UUID]:
    """The plugins that name the integrations a chat of the agent uses for
    the user, the list that chat tool construction reads."""
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
    return policy.agent_plugin_ids(
        db_session,
        user.id,
        persona_id,
        links,
        for_everyone_only=user.is_anonymous,
    )


def set_plugin_enabled__no_commit(
    user: User, plugin_id: UUID, enabled: bool, db_session: Session
) -> None:
    integration, state = _accessible_integration(user, plugin_id, db_session)
    if not enabled and state.installation_policy == PluginInstallationPolicy.REQUIRED:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Your admin made this plugin Required. You cannot turn it off.",
        )
    set_integration_preferences__no_commit(
        user.id, [integration.id], enabled, db_session
    )


def set_company_policy__no_commit(
    integration: Integration, policy: PluginInstallationPolicy, db_session: Session
) -> set[UUID]:
    """Set the company install setting of a locked integration. Returns the
    affected users."""
    before = affected_user_ids_for_integrations([integration.id], db_session)
    integration.installation_policy = policy
    db_session.flush()
    return before | affected_user_ids_for_integrations([integration.id], db_session)


def set_installation_policy__no_commit(
    plugin_id: UUID, policy: PluginInstallationPolicy, db_session: Session
) -> set[UUID]:
    """Set the company install setting. NOT_AVAILABLE makes the integration
    private: only its owner and its shares keep access. The caller checked
    organization-wide manage-actions. Returns the affected users."""
    integration = _integration_of_plugin(plugin_id, db_session, lock=True)
    return set_company_policy__no_commit(integration, policy, db_session)


def _owned_private_integration(
    user: User,
    plugin_id: UUID,
    db_session: Session,
    *,
    token_may_manage: bool,
    lock: bool,
) -> Integration:
    """The private integration of the plugin, which the user owns or manages
    as an organization-wide action manager. ``token_may_manage`` is False
    when the token of the request does not allow Manage actions."""
    integration = _integration_of_plugin(plugin_id, db_session, lock=lock)
    if integration.owner_user_id != user.id and not (
        token_may_manage and has_global_permission(user, Permission.MANAGE_ACTIONS)
    ):
        if _user_state(user, integration, db_session) is not None:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Only the owner of this plugin can share or publish it.",
            )
        raise _not_found()
    if integration.installation_policy != PluginInstallationPolicy.NOT_AVAILABLE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This plugin is available to the organization. Change its install "
            "setting instead.",
        )
    return integration


def plugin_access_view(
    user: User, plugin_id: UUID, db_session: Session, *, token_may_manage: bool
) -> PluginAccessView:
    integration = _owned_private_integration(
        user, plugin_id, db_session, token_may_manage=token_may_manage, lock=False
    )
    shares = load_integration_shares(integration.id, db_session)
    return PluginAccessView(
        plugin_id=plugin_id,
        user_shares=[
            PluginUserShareView(
                user_id=share.user_id, email=share.email, permission=share.permission
            )
            for share in shares.user_shares
        ],
        group_shares=[
            PluginGroupShareView(
                group_id=share.group_id,
                group_name=share.group_name,
                permission=share.permission,
            )
            for share in shares.group_shares
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
    """Replace the shares of the integration. Each share lets a person use
    the integration, so each is saved as a viewer. The Sharing setting and
    the group scope rules of skills apply. Returns the affected users."""
    integration = _owned_private_integration(
        user, plugin_id, db_session, token_may_manage=token_may_manage, lock=True
    )
    return share_integration__no_commit(
        user,
        integration,
        [share.user_id for share in request.user_shares],
        [share.group_id for share in request.group_shares],
        db_session,
    )


def share_integration__no_commit(
    user: User,
    integration: Integration,
    user_ids: Collection[UUID],
    group_ids: Collection[int],
    db_session: Session,
) -> set[UUID]:
    """Replace the shares of a locked integration that the caller checked
    the user may share. Returns the affected users."""
    before = affected_user_ids_for_integrations([integration.id], db_session)
    replace_integration_shares__no_commit(
        integration, user_ids, group_ids, user, db_session
    )
    return before | affected_user_ids_for_integrations([integration.id], db_session)


def publish_plugin_for_user__no_commit(
    user: User,
    plugin_id: UUID,
    db_session: Session,
    *,
    token_may_manage: bool,
) -> tuple[str, set[UUID]]:
    """Make the private integration Available to the organization. Only an
    organization-wide action manager does this. The shares stay. Returns the
    name of the plugin and the affected users."""
    integration = _owned_private_integration(
        user, plugin_id, db_session, token_may_manage=token_may_manage, lock=True
    )
    affected = publish_integration__no_commit(
        user, integration, db_session, token_may_manage=token_may_manage
    )
    return get_plugin_names(db_session, [plugin_id])[plugin_id], affected


def publish_integration__no_commit(
    user: User, integration: Integration, db_session: Session, *, token_may_manage: bool
) -> set[UUID]:
    """Make a locked private integration Available to the organization.
    Returns the affected users."""
    if not token_may_manage or not has_global_permission(
        user, Permission.MANAGE_ACTIONS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide action manager can make an integration "
            "available to the organization.",
        )
    return set_company_policy__no_commit(
        integration, PluginInstallationPolicy.AVAILABLE, db_session
    )
