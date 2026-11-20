"""The access settings of an integration: the user's on/off choice, the
company install setting, the shares and publishing. Each function flushes
and never commits."""

from collections.abc import Collection, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.integration_access import (
    affected_user_ids_for_integrations,
    load_integration_shares,
    load_user_integration_states,
    replace_integration_shares__no_commit,
    set_integration_group_settings__no_commit,
    set_integration_preferences__no_commit,
)
from onyx.db.models import Integration, User
from onyx.db.persona import get_persona_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.policy import agent_integration_ids, persona_link_settings
from onyx.server.features.integrations.models import (
    IntegrationGroupShare,
    IntegrationSharesView,
    IntegrationUserShare,
)


def agent_integration_ids_for_user(
    user: User, persona_id: int, db_session: Session
) -> list[int]:
    """The integrations a chat of the agent uses for the user, the list that
    chat tool construction reads."""
    try:
        get_persona_by_id(persona_id, user, db_session, is_for_edit=False)
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.PERSONA_NOT_FOUND,
            f"Agent with ID {persona_id} does not exist",
        ) from e
    return agent_integration_ids(
        db_session,
        user.id,
        persona_id,
        persona_link_settings(db_session, persona_id),
        for_everyone_only=user.is_anonymous,
    )


def set_integration_enabled__no_commit(
    user: User, integration_id: int, enabled: bool, db_session: Session
) -> None:
    """Save the user's on/off choice. NOT_FOUND when the user has no
    access."""
    states = load_user_integration_states([user.id], db_session, [integration_id])
    if not states:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")
    if (
        not enabled
        and states[0].installation_policy == PluginInstallationPolicy.REQUIRED
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Your admin made this integration Required. You cannot turn it off.",
        )
    set_integration_preferences__no_commit(
        user.id, [integration_id], enabled, db_session
    )


def set_company_policy__no_commit(
    integration: Integration, policy: PluginInstallationPolicy, db_session: Session
) -> set[UUID]:
    """Set the company install setting of a locked integration.
    NOT_AVAILABLE makes it private: only its owner and its shares keep
    access. Returns the affected users."""
    before = affected_user_ids_for_integrations([integration.id], db_session)
    integration.installation_policy = policy
    db_session.flush()
    return before | affected_user_ids_for_integrations([integration.id], db_session)


def set_group_settings__no_commit(
    user: User,
    integration: Integration,
    settings: Mapping[int, PluginInstallationPolicy | None],
    db_session: Session,
) -> set[UUID]:
    """Set the install setting of groups on a locked integration. The most
    open setting of a user's groups and the company setting wins. Returns the
    affected users."""
    before = affected_user_ids_for_integrations([integration.id], db_session)
    set_integration_group_settings__no_commit(integration, settings, user, db_session)
    return before | affected_user_ids_for_integrations([integration.id], db_session)


def check_private(integration: Integration) -> None:
    """Only a private integration has shares and can be published."""
    if integration.installation_policy != PluginInstallationPolicy.NOT_AVAILABLE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This integration is available to the organization. Change its "
            "install setting instead.",
        )


def integration_shares_view(
    integration: Integration, db_session: Session
) -> IntegrationSharesView:
    shares = load_integration_shares(integration.id, db_session)
    return IntegrationSharesView(
        integration_id=integration.id,
        user_shares=[
            IntegrationUserShare(user_id=share.user_id, email=share.email)
            for share in shares.user_shares
        ],
        group_shares=[
            IntegrationGroupShare(group_id=share.group_id, group_name=share.group_name)
            for share in shares.group_shares
        ],
    )


def share_integration__no_commit(
    user: User,
    integration: Integration,
    user_ids: Collection[UUID],
    group_ids: Collection[int],
    db_session: Session,
) -> set[UUID]:
    """Replace the shares of a locked integration that the caller checked
    the user manages. Each share lets a person use the integration. The
    Sharing setting and the group scope rules of skills apply. Returns the
    affected users."""
    before = affected_user_ids_for_integrations([integration.id], db_session)
    replace_integration_shares__no_commit(
        integration, user_ids, group_ids, user, db_session
    )
    return before | affected_user_ids_for_integrations([integration.id], db_session)


def publish_integration__no_commit(
    user: User, integration: Integration, db_session: Session
) -> set[UUID]:
    """Make a locked private integration Available to the organization. The
    shares stay. Returns the affected users."""
    if not has_global_permission(user, Permission.MANAGE_ACTIONS):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide action manager can make an integration "
            "available to the organization.",
        )
    return set_company_policy__no_commit(
        integration, PluginInstallationPolicy.AVAILABLE, db_session
    )
