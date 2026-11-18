"""Routes of a plugin that holds only integrations: the plugins an agent
runs for the user, the user's on/off switch, the shares and publishing of a private plugin, and the install
setting of an Organization library plugin."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission, token_allows
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.integrations.plugin_settings import (
    agent_plugin_ids,
    member_plugin_state,
    plugin_access_view,
    publish_plugin_for_user__no_commit,
    set_installation_policy__no_commit,
    set_plugin_enabled__no_commit,
    share_plugin__no_commit,
)
from onyx.integrations.service import reload_craft_sessions
from onyx.server.features.integrations.models import (
    MemberPluginState,
    PluginAccessUpdate,
    PluginAccessView,
    PluginEnableRequest,
    PluginInstallationPolicyUpdate,
)

router = APIRouter(prefix="/plugins")
admin_router = APIRouter(prefix="/admin/plugins")

_member = require_permission(Permission.BASIC_ACCESS)


@router.get("/agents/{persona_id}")
def get_agent_plugin_ids(
    persona_id: int,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> list[UUID]:
    return agent_plugin_ids(user, persona_id, db_session)


@router.put("/{plugin_id}/enabled")
def set_plugin_enabled(
    plugin_id: UUID,
    request: PluginEnableRequest,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> MemberPluginState:
    set_plugin_enabled__no_commit(user, plugin_id, request.enabled, db_session)
    db_session.commit()
    reload_craft_sessions({user.id}, db_session)
    return member_plugin_state(user, plugin_id, db_session)


@router.get("/{plugin_id}/access")
def get_plugin_access(
    http_request: Request,
    plugin_id: UUID,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> PluginAccessView:
    return plugin_access_view(
        user,
        plugin_id,
        db_session,
        token_may_manage=token_allows(http_request, Permission.MANAGE_ACTIONS),
    )


@router.put("/{plugin_id}/access")
def share_plugin(
    http_request: Request,
    plugin_id: UUID,
    request: PluginAccessUpdate,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> PluginAccessView:
    token_may_manage = token_allows(http_request, Permission.MANAGE_ACTIONS)
    affected = share_plugin__no_commit(
        user, plugin_id, request, db_session, token_may_manage=token_may_manage
    )
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return plugin_access_view(
        user, plugin_id, db_session, token_may_manage=token_may_manage
    )


@router.post("/{plugin_id}/publish", status_code=204)
def publish_plugin(
    http_request: Request,
    plugin_id: UUID,
    user: User = Depends(_member),
    db_session: Session = Depends(get_session),
) -> Response:
    affected = publish_plugin_for_user__no_commit(
        user,
        plugin_id,
        db_session,
        token_may_manage=token_allows(http_request, Permission.MANAGE_ACTIONS),
    )
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return Response(status_code=204)


@admin_router.put("/{plugin_id}/installation-policy")
def set_plugin_installation_policy(
    plugin_id: UUID,
    request: PluginInstallationPolicyUpdate,
    user: User = Depends(require_permission(Permission.MANAGE_ACTIONS)),
    db_session: Session = Depends(get_session),
) -> PluginInstallationPolicyUpdate:
    affected = set_installation_policy__no_commit(
        user, plugin_id, request.installation_policy, db_session
    )
    db_session.commit()
    reload_craft_sessions(affected, db_session)
    return request
