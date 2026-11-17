"""The one sign-in flow for integrations."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.integration import get_integration_by_id
from onyx.db.integration_connection import user_can_see_integration
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.oauth import (
    complete_integration_oauth,
    start_integration_oauth,
)
from onyx.oauth.models import SafeOAuthReturnPath

router = APIRouter(prefix="/integrations")


class IntegrationOAuthStartRequest(BaseModel):
    return_path: SafeOAuthReturnPath | None = None


class IntegrationOAuthStartResponse(BaseModel):
    authorization_url: str


class IntegrationOAuthCallbackRequest(BaseModel):
    code: str
    state: str


class IntegrationOAuthCallbackResponse(BaseModel):
    integration_id: int
    return_path: str | None


@router.post("/{integration_id}/oauth/start")
def start_oauth(
    integration_id: int,
    request: IntegrationOAuthStartRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IntegrationOAuthStartResponse:
    integration = get_integration_by_id(integration_id, db_session)
    if integration is None or not (
        has_global_permission(user, Permission.MANAGE_ACTIONS)
        or user_can_see_integration(db_session, integration_id, user.id)
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")
    return IntegrationOAuthStartResponse(
        authorization_url=start_integration_oauth(
            integration, user, db_session, request.return_path
        )
    )


@router.post("/oauth/callback")
def oauth_callback(
    request: IntegrationOAuthCallbackRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IntegrationOAuthCallbackResponse:
    result = complete_integration_oauth(request.code, request.state, user, db_session)
    return IntegrationOAuthCallbackResponse(
        integration_id=result.integration_id, return_path=result.return_path
    )
