"""The one sign-in flow for integrations."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission, token_allows
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.integrations.connections import check_connection_mode
from onyx.integrations.oauth import (
    IntegrationOAuthCallbackResult,
    complete_integration_oauth,
    start_integration_oauth,
)
from onyx.integrations.service import (
    craft_users_of_integration,
    get_viewable_integration,
    reload_craft_sessions,
)
from onyx.server.features.integrations.models import (
    IntegrationOAuthCallbackRequest,
    IntegrationOAuthStartRequest,
    IntegrationOAuthStartResponse,
)

router = APIRouter(prefix="/integrations")


@router.post("/{integration_id}/oauth/start")
def start_oauth(
    http_request: Request,
    integration_id: int,
    request: IntegrationOAuthStartRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IntegrationOAuthStartResponse:
    integration = get_viewable_integration(user, integration_id, db_session)
    check_connection_mode(integration, request.organization)
    return IntegrationOAuthStartResponse(
        authorization_url=start_integration_oauth(
            integration,
            user,
            db_session,
            request.return_path,
            token_may_manage=token_allows(http_request, Permission.MANAGE_ACTIONS),
        )
    )


@router.post("/oauth/callback")
def oauth_callback(
    http_request: Request,
    request: IntegrationOAuthCallbackRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IntegrationOAuthCallbackResult:
    result = complete_integration_oauth(
        request.code,
        request.state,
        user,
        db_session,
        token_may_manage=token_allows(http_request, Permission.MANAGE_ACTIONS),
    )
    reload_craft_sessions(
        (
            craft_users_of_integration(result.integration_id, db_session)
            if result.for_organization
            else {user.id}
        ),
        db_session,
    )
    return result
