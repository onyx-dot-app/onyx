"""Member routes of integrations: the list with status, the user's on/off
choice, connect and disconnect, the Always allow choices, the agent catalog
and the integrations of an agent. The share and publish routes are here too;
they need Manage actions."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.integration_connection import delete_connection__no_commit
from onyx.db.models import User
from onyx.integrations.access import (
    agent_integration_ids_for_user,
    check_private,
    integration_shares_view,
    publish_integration__no_commit,
    set_integration_enabled__no_commit,
    share_integration__no_commit,
)
from onyx.integrations.connections import (
    IntegrationStatus,
    integration_status,
)
from onyx.integrations.service import (
    action_grants,
    agent_catalog,
    get_manageable_integration,
    get_member_integration,
    list_member_integrations,
    member_detail,
    member_view,
    reload_craft_sessions,
    save_connection_fields__no_commit,
    set_action_grants__no_commit,
)
from onyx.server.features.integrations.models import (
    ActionGrantsResponse,
    ActionGrantsUpdate,
    AgentIntegrationOption,
    ConnectionFieldsRequest,
    IntegrationEnableRequest,
    IntegrationInstallationPolicy,
    IntegrationSharesUpdate,
    IntegrationSharesView,
    MemberIntegration,
    MemberIntegrationDetail,
)

router = APIRouter(prefix="/integrations")
action_policies_router = APIRouter(prefix="/action-policies")
# The released mobile app reads the integrations of an agent here.
mobile_plugins_router = APIRouter(prefix="/plugins")

_member = require_permission(Permission.BASIC_ACCESS)
_manager = require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)


@router.get("")
def list_integrations_for_member(
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> list[MemberIntegration]:
    return list_member_integrations(user, db_session)


@router.get("/agent-catalog")
def get_agent_catalog(
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> list[AgentIntegrationOption]:
    return agent_catalog(user, db_session)


@router.get("/agents/{persona_id}")
def get_agent_integration_ids(
    persona_id: int,
    # An anonymous chat reads its integrations too: only those open to
    # everyone (agent_integration_ids_for_user).
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[int]:
    """The integrations that a chat of the agent uses for the user."""
    return agent_integration_ids_for_user(user, persona_id, db_session)


@mobile_plugins_router.get("/agents/{persona_id}")
def get_agent_integration_ids_for_mobile(
    persona_id: int,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> list[str]:
    """The integration ids as text. The mobile app sends each one back in a
    ``plugin`` tool option."""
    return [
        str(integration_id)
        for integration_id in agent_integration_ids_for_user(
            user, persona_id, db_session
        )
    ]


@router.get("/{integration_id}")
def get_integration_for_member(
    integration_id: int,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> MemberIntegrationDetail:
    integration = get_member_integration(user, integration_id, db_session)
    return member_detail(user, integration, db_session)


@router.put("/{integration_id}/enabled")
def set_integration_enabled(
    integration_id: int,
    request: IntegrationEnableRequest,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> MemberIntegration:
    set_integration_enabled__no_commit(
        user, integration_id, request.enabled, db_session
    )
    db_session.commit()
    reload_craft_sessions({user.id}, db_session)
    return member_view(
        user, get_member_integration(user, integration_id, db_session), db_session
    )


@router.get("/{integration_id}/access")
def get_integration_shares(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationSharesView:
    integration = get_manageable_integration(user, integration_id, db_session)
    check_private(integration)
    return integration_shares_view(integration, db_session)


@router.put("/{integration_id}/access")
def set_integration_shares(
    integration_id: int,
    request: IntegrationSharesUpdate,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationSharesView:
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    check_private(integration)
    affected = share_integration__no_commit(
        user, integration, request.user_ids, request.group_ids, db_session
    )
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return integration_shares_view(integration, db_session)


@router.post("/{integration_id}/publish")
def publish_integration(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationInstallationPolicy:
    """Make a private integration Available to the organization. Only an
    organization-wide action manager does this."""
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    check_private(integration)
    affected = publish_integration__no_commit(user, integration, db_session)
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return IntegrationInstallationPolicy(
        installation_policy=integration.installation_policy
    )


@router.put("/{integration_id}/connection")
def save_member_connection(
    integration_id: int,
    request: ConnectionFieldsRequest,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> IntegrationStatus:
    integration = get_member_integration(user, integration_id, db_session)
    save_connection_fields__no_commit(integration, user, request.fields, db_session)
    db_session.commit()
    reload_craft_sessions({user.id}, db_session)
    return integration_status(integration, user, db_session)


@router.delete("/{integration_id}/connection")
def delete_member_connection(
    integration_id: int,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> IntegrationStatus:
    integration = get_member_integration(user, integration_id, db_session)
    delete_connection__no_commit(db_session, integration.id, user.id)
    db_session.commit()
    reload_craft_sessions({user.id}, db_session)
    return integration_status(integration, user, db_session)


@action_policies_router.get("/integration/{integration_id}")
def get_action_grants(
    integration_id: int,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> ActionGrantsResponse:
    integration = get_member_integration(user, integration_id, db_session)
    return action_grants(user, integration, db_session)


@action_policies_router.put("/integration/{integration_id}")
def save_action_grants(
    integration_id: int,
    request: ActionGrantsUpdate,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> ActionGrantsResponse:
    integration = get_member_integration(user, integration_id, db_session)
    set_action_grants__no_commit(user, integration, request.actions, db_session)
    db_session.commit()
    return action_grants(user, integration, db_session)
