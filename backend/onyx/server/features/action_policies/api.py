"""Personal action policy endpoints for one app or MCP server.

MCP servers serve chat and Craft, so their settings do not require Craft.
External apps exist only in Craft.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.action_policy import (
    get_gated_app_id,
    list_action_policies,
    save_user_action_policies,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import GatedAppKind, Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import (
    AppActionPolicies,
    AppActionPoliciesView,
    SaveActionPolicies,
)
from onyx.server.features.build.utils import is_craft_enabled_for_user

router = APIRouter(prefix="/action-policies")


def _require_kind_available(
    kind: Literal["external_app", "mcp_server"], user: User
) -> GatedAppKind:
    gated_kind = GatedAppKind[kind.upper()]
    if gated_kind is GatedAppKind.EXTERNAL_APP and not is_craft_enabled_for_user(user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Onyx Craft is not available"
        )
    return gated_kind


@router.get("/{kind}/{target_id}")
def get_personal_action_policies(
    kind: Literal["external_app", "mcp_server"],
    target_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AppActionPoliciesView:
    return list_action_policies(
        db_session, user, target=(_require_kind_available(kind, user), target_id)
    )[0]


@router.put("/{kind}/{target_id}")
def save_personal_action_policies(
    kind: Literal["external_app", "mcp_server"],
    target_id: int,
    request: SaveActionPolicies,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AppActionPoliciesView:
    gated_app_id = get_gated_app_id(
        db_session, _require_kind_available(kind, user), target_id
    )
    if gated_app_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "App is unavailable")
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
