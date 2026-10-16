"""Personal and workspace approval policy endpoints shared by apps and MCP."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.action_policy import (
    list_action_policies,
    replace_workspace_action_policies,
    save_user_action_policies,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import GatedAppKind, Permission
from onyx.db.external_app import get_skills_for_external_app
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.external_apps.models import (
    AppActionPolicies,
    AppActionPoliciesView,
    SaveActionPolicies,
    WorkspaceActionPoliciesUpdate,
)
from onyx.skills.push import push_skills_for_users

router = APIRouter(prefix="/action-policies")
admin_router = APIRouter(prefix="/action-policies")


@router.get("/{kind}/{target_id}")
def get_personal_action_policies(
    kind: Literal["external_app", "mcp_server"],
    target_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AppActionPoliciesView:
    data = list_action_policies(
        db_session, user, target=(GatedAppKind[kind.upper()], target_id)
    )[0]
    return data


@admin_router.get("/{kind}/{target_id}")
def get_workspace_action_policies(
    kind: Literal["external_app", "mcp_server"],
    target_id: int,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AppActionPoliciesView:
    data = list_action_policies(
        db_session, user, target=(GatedAppKind[kind.upper()], target_id), admin=True
    )[0]
    return data


@router.get("")
def list_personal_action_policies(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[AppActionPoliciesView]:
    return list_action_policies(db_session, user)


@router.put("/{gated_app_id}")
def save_personal_action_policies(
    gated_app_id: int,
    request: SaveActionPolicies,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AppActionPoliciesView:
    save_user_action_policies(
        db_session,
        user,
        AppActionPolicies(
            gated_app_id=gated_app_id, action_policies=request.action_policies
        ),
    )
    view = list_action_policies(db_session, user, gated_app_id=gated_app_id)[0]
    db_session.commit()
    return view


@admin_router.get("")
def list_workspace_action_policies(
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[AppActionPoliciesView]:
    return list_action_policies(db_session, user, admin=True)


@admin_router.put("/{gated_app_id}")
def update_workspace_action_policies(
    gated_app_id: int,
    request: WorkspaceActionPoliciesUpdate,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AppActionPoliciesView:
    replace_workspace_action_policies(
        db_session,
        gated_app_id,
        policies=request.action_policies,
        users_can_manage=request.users_can_manage_policies,
    )
    view = list_action_policies(
        db_session, user, gated_app_id=gated_app_id, admin=True
    )[0]
    affected: set[UUID] = set()
    if request.action_policies is not None and view.kind == "external_app":
        for skill in get_skills_for_external_app(db_session, view.target_id):
            affected.update(affected_user_ids_for_skill(skill, db_session))
    db_session.commit()
    if affected:
        push_skills_for_users(affected, db_session)
        db_session.commit()
    return view
