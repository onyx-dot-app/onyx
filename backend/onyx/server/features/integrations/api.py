"""Member routes of integrations: the list with status, connect and
disconnect, the Always allow choices and the agent catalog."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.integration_connection import delete_connection__no_commit
from onyx.db.models import User
from onyx.integrations.connections import (
    IntegrationStatus,
    integration_status,
)
from onyx.integrations.service import (
    action_grants,
    agent_catalog,
    get_member_integration,
    list_member_integrations,
    member_detail,
    reload_craft_sessions,
    save_connection_fields__no_commit,
    set_action_grants__no_commit,
)
from onyx.server.features.integrations.models import (
    ActionGrantsResponse,
    ActionGrantsUpdate,
    AgentPluginOption,
    ConnectionFieldsRequest,
    MemberIntegration,
    MemberIntegrationDetail,
)

router = APIRouter(prefix="/integrations")
action_policies_router = APIRouter(prefix="/action-policies")

_member = require_permission(Permission.BASIC_ACCESS)


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
) -> list[AgentPluginOption]:
    return agent_catalog(user, db_session)


@router.get("/{integration_id}")
def get_integration_for_member(
    integration_id: int,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> MemberIntegrationDetail:
    integration = get_member_integration(user, integration_id, db_session)
    return member_detail(user, integration, db_session)


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
