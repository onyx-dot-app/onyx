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
from onyx.configs.constants import DocumentSource
from onyx.db.engine import get_current_tenant_id
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

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

    if connector == DocumentSource.SLACK:
        oauth_url = SlackOAuth.generate_oauth_url(oauth_state)
        session = SlackOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    elif connector == DocumentSource.CONFLUENCE:
        oauth_url = ConfluenceCloudOAuth.generate_dev_oauth_url(oauth_state)
        session = ConfluenceCloudOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    # elif connector == DocumentSource.JIRA:
    #     oauth_url = JiraCloudOAuth.generate_dev_oauth_url(oauth_state)
    elif connector == DocumentSource.GOOGLE_DRIVE:
        oauth_url = GoogleDriveOAuth.generate_oauth_url(oauth_state)
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

    r = get_redis_client(tenant_id=tenant_id)

    # store important session state to retrieve when the user is redirected back
    # 10 min is the max we want an oauth flow to be valid
    r.set(f"da_oauth:{oauth_uuid_str}", session, ex=600)

    return JSONResponse(content={"url": oauth_url})


# Work in progress
# @router.post("/connector/confluence/callback")
# def handle_confluence_oauth_callback(
#     code: str,
#     state: str,
#     user: User = Depends(current_user),
#     db_session: Session = Depends(get_session),
#     tenant_id: str | None = Depends(get_current_tenant_id),
# ) -> JSONResponse:
#     if not ConfluenceCloudOAuth.CLIENT_ID or not ConfluenceCloudOAuth.CLIENT_SECRET:
#         raise HTTPException(
#             status_code=500,
#             detail="Confluence client ID or client secret is not configured."
#         )

#     r = get_redis_client(tenant_id=tenant_id)

#     # recover the state
#     padded_state = state + '=' * (-len(state) % 4)  # Add padding back (Base64 decoding requires padding)
#     uuid_bytes = base64.urlsafe_b64decode(padded_state)  # Decode the Base64 string back to bytes

#     # Convert bytes back to a UUID
#     oauth_uuid = uuid.UUID(bytes=uuid_bytes)
#     oauth_uuid_str = str(oauth_uuid)

#     r_key = f"da_oauth:{oauth_uuid_str}"

#     result = r.get(r_key)
#     if not result:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Confluence OAuth failed - OAuth state key not found: key={r_key}"
#         )

#     try:
#         session = ConfluenceCloudOAuth.parse_session(result)

#         # Exchange the authorization code for an access token
#         response = requests.post(
#             ConfluenceCloudOAuth.TOKEN_URL,
#             headers={"Content-Type": "application/x-www-form-urlencoded"},
#             data={
#                 "client_id": ConfluenceCloudOAuth.CLIENT_ID,
#                 "client_secret": ConfluenceCloudOAuth.CLIENT_SECRET,
#                 "code": code,
#                 "redirect_uri": ConfluenceCloudOAuth.DEV_REDIRECT_URI,
#             },
#         )

#         response_data = response.json()

#         if not response_data.get("ok"):
#             raise HTTPException(
#                 status_code=400,
#                 detail=f"ConfluenceCloudOAuth OAuth failed: {response_data.get('error')}"
#             )

#         # Extract token and team information
#         access_token: str = response_data.get("access_token")
#         team_id: str = response_data.get("team", {}).get("id")
#         authed_user_id: str = response_data.get("authed_user", {}).get("id")

#         credential_info = CredentialBase(
#             credential_json={"slack_bot_token": access_token},
#             admin_public=True,
#             source=DocumentSource.CONFLUENCE,
#             name="Confluence OAuth",
#         )

#         logger.info(f"Slack access token: {access_token}")

#         credential = create_credential(credential_info, user, db_session)

#         logger.info(f"new_credential_id={credential.id}")
#     except Exception as e:
#         return JSONResponse(
#             status_code=500,
#             content={
#                 "success": False,
#                 "message": f"An error occurred during Slack OAuth: {str(e)}",
#             },
#         )
#     finally:
#         r.delete(r_key)

#     # return the result
#     return JSONResponse(
#         content={
#             "success": True,
#             "message": "Slack OAuth completed successfully.",
#             "team_id": team_id,
#             "authed_user_id": authed_user_id,
#             "redirect_on_success": session.redirect_on_success,
#         }
#     )
