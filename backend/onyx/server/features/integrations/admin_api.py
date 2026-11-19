"""Admin routes of integrations. A scoped action manager reaches them too
and manages only the private integrations that it owns."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.integration_connection import delete_connection__no_commit
from onyx.db.models import User
from onyx.integrations.access import (
    set_company_policy__no_commit,
    set_group_settings__no_commit,
)
from onyx.integrations.connections import (
    IntegrationStatus,
)
from onyx.integrations.service import (
    admin_actions,
    admin_detail,
    craft_users_of_integration,
    create_integration__no_commit,
    delete_integration_for_user__no_commit,
    get_manageable_integration,
    get_viewable_integration,
    list_admin_integrations,
    organization_status,
    preset_views,
    refresh_actions__no_commit,
    reload_craft_sessions,
    save_connection_fields__no_commit,
    set_admin_actions__no_commit,
    update_integration__no_commit,
)
from onyx.server.features.integrations.models import (
    AdminIntegration,
    AdminIntegrationDetail,
    ConnectionFieldsRequest,
    IntegrationActionsResponse,
    IntegrationActionsUpdate,
    IntegrationCreate,
    IntegrationGroupSettingsUpdate,
    IntegrationInstallationPolicy,
    IntegrationUpdate,
    PresetView,
)

router = APIRouter(prefix="/admin/integrations")

_manager = require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)


@router.get("")
def list_integrations_admin(
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> list[AdminIntegration]:
    return list_admin_integrations(user, db_session)


@router.get("/presets")
def list_integration_presets(
    user: User = Depends(_manager),
) -> list[PresetView]:
    return preset_views(user)


@router.post("")
def create_integration(
    request: IntegrationCreate,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> AdminIntegrationDetail:
    integration = create_integration__no_commit(user, request, db_session)
    db_session.commit()
    reload_craft_sessions(
        craft_users_of_integration(integration.id, db_session), db_session
    )
    return admin_detail(user, integration, db_session)


@router.get("/{integration_id}")
def get_integration_admin(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> AdminIntegrationDetail:
    integration = get_viewable_integration(user, integration_id, db_session)
    return admin_detail(user, integration, db_session)


@router.patch("/{integration_id}")
def update_integration(
    integration_id: int,
    request: IntegrationUpdate,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> AdminIntegrationDetail:
    integration = update_integration__no_commit(
        user, integration_id, request, db_session
    )
    db_session.commit()
    reload_craft_sessions(
        craft_users_of_integration(integration.id, db_session), db_session
    )
    return admin_detail(user, integration, db_session)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> Response:
    affected = craft_users_of_integration(integration_id, db_session)
    delete_integration_for_user__no_commit(user, integration_id, db_session)
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return Response(status_code=204)


@router.put("/{integration_id}/installation-policy")
def set_integration_installation_policy(
    integration_id: int,
    request: IntegrationInstallationPolicy,
    user: User = Depends(require_permission(Permission.MANAGE_ACTIONS)),
    db_session: Session = Depends(get_session),
) -> IntegrationInstallationPolicy:
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    affected = set_company_policy__no_commit(
        integration, request.installation_policy, db_session
    )
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return request


@router.put("/{integration_id}/group-settings")
def set_integration_group_settings(
    integration_id: int,
    request: IntegrationGroupSettingsUpdate,
    user: User = Depends(require_permission(Permission.MANAGE_ACTIONS)),
    db_session: Session = Depends(get_session),
) -> AdminIntegrationDetail:
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    affected = set_group_settings__no_commit(
        user,
        integration,
        {
            setting.group_id: setting.installation_policy
            for setting in request.group_settings
        },
        db_session,
    )
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return admin_detail(user, integration, db_session)


@router.get("/{integration_id}/actions")
def get_integration_actions(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationActionsResponse:
    integration = get_viewable_integration(user, integration_id, db_session)
    return admin_actions(integration, db_session)


@router.put("/{integration_id}/actions")
def set_integration_actions(
    integration_id: int,
    request: IntegrationActionsUpdate,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationActionsResponse:
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    set_admin_actions__no_commit(integration, request, db_session)
    db_session.commit()
    reload_craft_sessions(
        craft_users_of_integration(integration.id, db_session), db_session
    )
    return admin_actions(integration, db_session)


@router.post("/{integration_id}/actions/refresh")
def refresh_integration_actions(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationActionsResponse:
    integration = get_manageable_integration(user, integration_id, db_session)
    refresh_actions__no_commit(user, integration, db_session)
    db_session.commit()
    reload_craft_sessions(
        craft_users_of_integration(integration.id, db_session), db_session
    )
    return admin_actions(integration, db_session)


@router.put("/{integration_id}/organization-connection")
def save_organization_connection(
    integration_id: int,
    request: ConnectionFieldsRequest,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationStatus:
    integration = get_manageable_integration(user, integration_id, db_session)
    save_connection_fields__no_commit(integration, None, request.fields, db_session)
    db_session.commit()
    reload_craft_sessions(
        craft_users_of_integration(integration.id, db_session), db_session
    )
    return organization_status(integration, db_session)


@router.delete("/{integration_id}/organization-connection")
def delete_organization_connection(
    integration_id: int,
    user: User = Depends(_manager),
    db_session: Session = Depends(get_session),
) -> IntegrationStatus:
    integration = get_manageable_integration(user, integration_id, db_session)
    delete_connection__no_commit(db_session, integration.id, None)
    db_session.commit()
    reload_craft_sessions(
        craft_users_of_integration(integration.id, db_session), db_session
    )
    return organization_status(integration, db_session)
