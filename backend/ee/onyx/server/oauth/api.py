import base64
import uuid

from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ee.onyx.server.oauth.api_router import router
from ee.onyx.server.oauth.confluence_cloud import ConfluenceCloudOAuth
from ee.onyx.server.oauth.google_drive import GoogleDriveOAuth
from ee.onyx.server.oauth.slack import SlackOAuth
from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.constants import DocumentSource
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


@router.post("/prepare-authorization-request")
def prepare_authorization_request(
    connector: DocumentSource,
    redirect_on_success: str | None,
    user: User = Depends(current_admin_user),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> JSONResponse:
    """Used by the frontend to generate the url for the user's browser during auth request.

    Example: https://www.oauth.com/oauth2-servers/authorization/the-authorization-request/
    """

    # create random oauth state param for security and to retrieve user data later
    oauth_uuid = uuid.uuid4()
    oauth_uuid_str = str(oauth_uuid)

    # urlsafe b64 encode the uuid for the oauth url
    oauth_state = (
        base64.urlsafe_b64encode(oauth_uuid.bytes).rstrip(b"=").decode("utf-8")
    )

    session: str | None = None
    if connector == DocumentSource.SLACK:
        if not DEV_MODE:
            oauth_url = SlackOAuth.generate_oauth_url(oauth_state)
        else:
            oauth_url = SlackOAuth.generate_dev_oauth_url(oauth_state)

        session = SlackOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    elif connector == DocumentSource.CONFLUENCE:
        if not DEV_MODE:
            oauth_url = ConfluenceCloudOAuth.generate_oauth_url(oauth_state)
        else:
            oauth_url = ConfluenceCloudOAuth.generate_dev_oauth_url(oauth_state)
        session = ConfluenceCloudOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    elif connector == DocumentSource.GOOGLE_DRIVE:
        if not DEV_MODE:
            oauth_url = GoogleDriveOAuth.generate_oauth_url(oauth_state)
        else:
            oauth_url = GoogleDriveOAuth.generate_dev_oauth_url(oauth_state)
        session = GoogleDriveOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    else:
        oauth_url = None

    if not oauth_url:
        raise HTTPException(
            status_code=404,
            detail=f"The document source type {connector} does not have OAuth implemented",
        )

    if not session:
        raise HTTPException(
            status_code=500,
            detail=f"The document source type {connector} failed to generate an OAuth session.",
        )

    r = get_redis_client(tenant_id=tenant_id)

    # store important session state to retrieve when the user is redirected back
    # 10 min is the max we want an oauth flow to be valid
    r.set(f"da_oauth:{oauth_uuid_str}", session, ex=600)

    return JSONResponse(content={"url": oauth_url})
