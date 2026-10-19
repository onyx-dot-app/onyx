"""Personal and workspace approval policy endpoints shared by apps and MCP."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.action_policy import (
    list_action_policies,
    save_user_action_policies,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import GatedAppKind, Permission
from onyx.db.models import User
from onyx.external_apps.models import (
    AppActionPolicies,
    AppActionPoliciesView,
    SaveActionPolicies,
)

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
