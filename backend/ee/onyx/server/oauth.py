import base64
import json
import uuid
from typing import Any
from typing import cast

import requests
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import OAUTH_CONFLUENCE_CLIENT_ID
from ee.onyx.configs.app_configs import OAUTH_CONFLUENCE_CLIENT_SECRET
from ee.onyx.configs.app_configs import OAUTH_GOOGLE_DRIVE_CLIENT_ID
from ee.onyx.configs.app_configs import OAUTH_GOOGLE_DRIVE_CLIENT_SECRET
from ee.onyx.configs.app_configs import OAUTH_SLACK_CLIENT_ID
from ee.onyx.configs.app_configs import OAUTH_SLACK_CLIENT_SECRET
from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.google_auth import get_google_oauth_creds
from onyx.connectors.google_utils.google_auth import sanitize_oauth_credentials
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)
from onyx.db.credentials import create_credential
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()

router = APIRouter(prefix="/oauth")


class SlackOAuth:
    # https://knock.app/blog/how-to-authenticate-users-in-slack-using-oauth
    # Example: https://api.slack.com/authentication/oauth-v2#exchanging

    class OAuthSession(BaseModel):
        """Stored in redis to be looked up on callback"""

        email: str
        redirect_on_success: str | None  # Where to send the user if OAuth flow succeeds

    CLIENT_ID = OAUTH_SLACK_CLIENT_ID
    CLIENT_SECRET = OAUTH_SLACK_CLIENT_SECRET

    TOKEN_URL = "https://slack.com/api/oauth.v2.access"

    # SCOPE is per https://docs.onyx.app/connectors/slack
    BOT_SCOPE = (
        "channels:history,"
        "channels:read,"
        "groups:history,"
        "groups:read,"
        "channels:join,"
        "im:history,"
        "users:read,"
        "users:read.email,"
        "usergroups:read"
    )

    REDIRECT_URI = f"{WEB_DOMAIN}/admin/connectors/slack/oauth/callback"
    DEV_REDIRECT_URI = f"https://redirectmeto.com/{REDIRECT_URI}"

    @classmethod
    def generate_oauth_url(cls, state: str) -> str:
        return cls._generate_oauth_url_helper(cls.REDIRECT_URI, state)

    @classmethod
    def generate_dev_oauth_url(cls, state: str) -> str:
        """dev mode workaround for localhost testing
        - https://www.nango.dev/blog/oauth-redirects-on-localhost-with-https
        """

        return cls._generate_oauth_url_helper(cls.DEV_REDIRECT_URI, state)

    @classmethod
    def _generate_oauth_url_helper(cls, redirect_uri: str, state: str) -> str:
        url = (
            f"https://slack.com/oauth/v2/authorize"
            f"?client_id={cls.CLIENT_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={cls.BOT_SCOPE}"
            f"&state={state}"
        )
        return url

    @classmethod
    def session_dump_json(cls, email: str, redirect_on_success: str | None) -> str:
        """Temporary state to store in redis. to be looked up on auth response.
        Returns a json string.
        """
        session = SlackOAuth.OAuthSession(
            email=email, redirect_on_success=redirect_on_success
        )
        return session.model_dump_json()

    @classmethod
    def parse_session(cls, session_json: str) -> OAuthSession:
        session = SlackOAuth.OAuthSession.model_validate_json(session_json)
        return session


class ConfluenceCloudOAuth:
    """work in progress"""

    # https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/

    class OAuthSession(BaseModel):
        """Stored in redis to be looked up on callback"""

        email: str
        redirect_on_success: str | None  # Where to send the user if OAuth flow succeeds

    CLIENT_ID = OAUTH_CONFLUENCE_CLIENT_ID
    CLIENT_SECRET = OAUTH_CONFLUENCE_CLIENT_SECRET
    TOKEN_URL = "https://auth.atlassian.com/oauth/token"

    # All read scopes per https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3LO-and-forge-apps/
    CONFLUENCE_OAUTH_SCOPE = (
        "read:confluence-props%20"
        "read:confluence-content.all%20"
        "read:confluence-content.summary%20"
        "read:confluence-content.permission%20"
        "read:confluence-user%20"
        "read:confluence-groups%20"
        "readonly:content.attachment:confluence"
    )

    REDIRECT_URI = f"{WEB_DOMAIN}/admin/connectors/confluence/oauth/callback"
    DEV_REDIRECT_URI = f"https://redirectmeto.com/{REDIRECT_URI}"

    # eventually for Confluence Data Center
    # oauth_url = (
    #     f"http://localhost:8090/rest/oauth/v2/authorize?client_id={CONFLUENCE_OAUTH_CLIENT_ID}"
    #     f"&scope={CONFLUENCE_OAUTH_SCOPE_2}"
    #     f"&redirect_uri={redirectme_uri}"
    # )

    @classmethod
    def generate_oauth_url(cls, state: str) -> str:
        return cls._generate_oauth_url_helper(cls.REDIRECT_URI, state)

    @classmethod
    def generate_dev_oauth_url(cls, state: str) -> str:
        """dev mode workaround for localhost testing
        - https://www.nango.dev/blog/oauth-redirects-on-localhost-with-https
        """
        return cls._generate_oauth_url_helper(cls.DEV_REDIRECT_URI, state)

    @classmethod
    def _generate_oauth_url_helper(cls, redirect_uri: str, state: str) -> str:
        url = (
            "https://auth.atlassian.com/authorize"
            f"?audience=api.atlassian.com"
            f"&client_id={cls.CLIENT_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={cls.CONFLUENCE_OAUTH_SCOPE}"
            f"&state={state}"
            "&response_type=code"
            "&prompt=consent"
        )
        return url

    @classmethod
    def session_dump_json(cls, email: str, redirect_on_success: str | None) -> str:
        """Temporary state to store in redis. to be looked up on auth response.
        Returns a json string.
        """
        session = ConfluenceCloudOAuth.OAuthSession(
            email=email, redirect_on_success=redirect_on_success
        )
        return session.model_dump_json()

    @classmethod
    def parse_session(cls, session_json: str) -> SlackOAuth.OAuthSession:
        session = SlackOAuth.OAuthSession.model_validate_json(session_json)
        return session


class GoogleDriveOAuth:
    # https://developers.google.com/identity/protocols/oauth2
    # https://developers.google.com/identity/protocols/oauth2/web-server

    class OAuthSession(BaseModel):
        """Stored in redis to be looked up on callback"""

        email: str
        redirect_on_success: str | None  # Where to send the user if OAuth flow succeeds

    CLIENT_ID = OAUTH_GOOGLE_DRIVE_CLIENT_ID
    CLIENT_SECRET = OAUTH_GOOGLE_DRIVE_CLIENT_SECRET

    TOKEN_URL = "https://oauth2.googleapis.com/token"

    # SCOPE is per https://docs.onyx.app/connectors/google-drive
    # TODO: Merge with or use google_utils.GOOGLE_SCOPES
    SCOPE = (
        "https://www.googleapis.com/auth/drive.readonly%20"
        "https://www.googleapis.com/auth/drive.metadata.readonly%20"
        "https://www.googleapis.com/auth/admin.directory.user.readonly%20"
        "https://www.googleapis.com/auth/admin.directory.group.readonly"
    )

    REDIRECT_URI = f"{WEB_DOMAIN}/admin/connectors/google-drive/oauth/callback"
    DEV_REDIRECT_URI = f"https://redirectmeto.com/{REDIRECT_URI}"

    @classmethod
    def generate_oauth_url(cls, state: str) -> str:
        return cls._generate_oauth_url_helper(cls.REDIRECT_URI, state)

    @classmethod
    def generate_dev_oauth_url(cls, state: str) -> str:
        """dev mode workaround for localhost testing
        - https://www.nango.dev/blog/oauth-redirects-on-localhost-with-https
        """

        return cls._generate_oauth_url_helper(cls.DEV_REDIRECT_URI, state)

    @classmethod
    def _generate_oauth_url_helper(cls, redirect_uri: str, state: str) -> str:
        # without prompt=consent, a refresh token is only issued the first time the user approves
        url = (
            f"https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={cls.CLIENT_ID}"
            f"&redirect_uri={redirect_uri}"
            "&response_type=code"
            f"&scope={cls.SCOPE}"
            "&access_type=offline"
            f"&state={state}"
            "&prompt=consent"
        )
        return url

    @classmethod
    def session_dump_json(cls, email: str, redirect_on_success: str | None) -> str:
        """Temporary state to store in redis. to be looked up on auth response.
        Returns a json string.
        """
        session = GoogleDriveOAuth.OAuthSession(
            email=email, redirect_on_success=redirect_on_success
        )
        return session.model_dump_json()

    @classmethod
    def parse_session(cls, session_json: str) -> OAuthSession:
        session = GoogleDriveOAuth.OAuthSession.model_validate_json(session_json)
        return session


@router.post("/prepare-authorization-request")
def prepare_authorization_request(
    connector: DocumentSource,
    redirect_on_success: str | None,
    user: User = Depends(current_user),
) -> JSONResponse:
    """Used by the frontend to generate the url for the user's browser during auth request.

    Example: https://www.oauth.com/oauth2-servers/authorization/the-authorization-request/
    """
    tenant_id = get_current_tenant_id()

    # create random oauth state param for security and to retrieve user data later
    oauth_uuid = uuid.uuid4()
    oauth_uuid_str = str(oauth_uuid)

    # urlsafe b64 encode the uuid for the oauth url
    oauth_state = (
        base64.urlsafe_b64encode(oauth_uuid.bytes).rstrip(b"=").decode("utf-8")
    )
    session: str

    if connector == DocumentSource.SLACK:
        oauth_url = SlackOAuth.generate_oauth_url(oauth_state)
        session = SlackOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    elif connector == DocumentSource.GOOGLE_DRIVE:
        oauth_url = GoogleDriveOAuth.generate_oauth_url(oauth_state)
        session = GoogleDriveOAuth.session_dump_json(
            email=user.email, redirect_on_success=redirect_on_success
        )
    # elif connector == DocumentSource.CONFLUENCE:
    #     oauth_url = ConfluenceCloudOAuth.generate_oauth_url(oauth_state)
    #     session = ConfluenceCloudOAuth.session_dump_json(
    #         email=user.email, redirect_on_success=redirect_on_success
    #     )
    # elif connector == DocumentSource.JIRA:
    #     oauth_url = JiraCloudOAuth.generate_dev_oauth_url(oauth_state)
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


@router.post("/connector/slack/callback")
def handle_slack_oauth_callback(
    code: str,
    state: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> JSONResponse:
    if not SlackOAuth.CLIENT_ID or not SlackOAuth.CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Slack client ID or client secret is not configured.",
        )

    r = get_redis_client()

    # recover the state
    padded_state = state + "=" * (
        -len(state) % 4
    )  # Add padding back (Base64 decoding requires padding)
    uuid_bytes = base64.urlsafe_b64decode(
        padded_state
    )  # Decode the Base64 string back to bytes

    # Convert bytes back to a UUID
    oauth_uuid = uuid.UUID(bytes=uuid_bytes)
    oauth_uuid_str = str(oauth_uuid)

    r_key = f"da_oauth:{oauth_uuid_str}"

    session_json_bytes = cast(bytes, r.get(r_key))
    if not session_json_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Slack OAuth failed - OAuth state key not found: key={r_key}",
        )

    session_json = session_json_bytes.decode("utf-8")
    try:
        session = SlackOAuth.parse_session(session_json)

        # Exchange the authorization code for an access token
        response = requests.post(
            SlackOAuth.TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": SlackOAuth.CLIENT_ID,
                "client_secret": SlackOAuth.CLIENT_SECRET,
                "code": code,
                "redirect_uri": SlackOAuth.REDIRECT_URI,
            },
        )

        response_data = response.json()

        if not response_data.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=f"Slack OAuth failed: {response_data.get('error')}",
            )

        # Extract token and team information
        access_token: str = response_data.get("access_token")
        team_id: str = response_data.get("team", {}).get("id")
        authed_user_id: str = response_data.get("authed_user", {}).get("id")

        credential_info = CredentialBase(
            credential_json={"slack_bot_token": access_token},
            admin_public=True,
            source=DocumentSource.SLACK,
            name="Slack OAuth",
        )

        create_credential(credential_info, user, db_session)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"An error occurred during Slack OAuth: {str(e)}",
            },
        )
    finally:
        r.delete(r_key)

    # return the result
    return JSONResponse(
        content={
            "success": True,
            "message": "Slack OAuth completed successfully.",
            "team_id": team_id,
            "authed_user_id": authed_user_id,
            "redirect_on_success": session.redirect_on_success,
        }
    )


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


@router.post("/connector/google-drive/callback")
def handle_google_drive_oauth_callback(
    code: str,
    state: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> JSONResponse:
    if not GoogleDriveOAuth.CLIENT_ID or not GoogleDriveOAuth.CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google Drive client ID or client secret is not configured.",
        )

    r = get_redis_client()

    # recover the state
    padded_state = state + "=" * (
        -len(state) % 4
    )  # Add padding back (Base64 decoding requires padding)
    uuid_bytes = base64.urlsafe_b64decode(
        padded_state
    )  # Decode the Base64 string back to bytes

    # Convert bytes back to a UUID
    oauth_uuid = uuid.UUID(bytes=uuid_bytes)
    oauth_uuid_str = str(oauth_uuid)

    r_key = f"da_oauth:{oauth_uuid_str}"

    session_json_bytes = cast(bytes, r.get(r_key))
    if not session_json_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Google Drive OAuth failed - OAuth state key not found: key={r_key}",
        )

    session_json = session_json_bytes.decode("utf-8")
    session: GoogleDriveOAuth.OAuthSession
    try:
        session = GoogleDriveOAuth.parse_session(session_json)

        # Exchange the authorization code for an access token
        response = requests.post(
            GoogleDriveOAuth.TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": GoogleDriveOAuth.CLIENT_ID,
                "client_secret": GoogleDriveOAuth.CLIENT_SECRET,
                "code": code,
                "redirect_uri": GoogleDriveOAuth.REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

        response.raise_for_status()

        authorization_response: dict[str, Any] = response.json()

        # the connector wants us to store the json in its authorized_user_info format
        # returned from OAuthCredentials.get_authorized_user_info().
        # So refresh immediately via get_google_oauth_creds with the params filled in
        # from fields in authorization_response to get the json we need
        authorized_user_info = {}
        authorized_user_info["client_id"] = OAUTH_GOOGLE_DRIVE_CLIENT_ID
        authorized_user_info["client_secret"] = OAUTH_GOOGLE_DRIVE_CLIENT_SECRET
        authorized_user_info["refresh_token"] = authorization_response["refresh_token"]

        token_json_str = json.dumps(authorized_user_info)
        oauth_creds = get_google_oauth_creds(
            token_json_str=token_json_str, source=DocumentSource.GOOGLE_DRIVE
        )
        if not oauth_creds:
            raise RuntimeError("get_google_oauth_creds returned None.")

        # save off the credentials
        oauth_creds_sanitized_json_str = sanitize_oauth_credentials(oauth_creds)

        credential_dict: dict[str, str] = {}
        credential_dict[DB_CREDENTIALS_DICT_TOKEN_KEY] = oauth_creds_sanitized_json_str
        credential_dict[DB_CREDENTIALS_PRIMARY_ADMIN_KEY] = session.email
        credential_dict[
            DB_CREDENTIALS_AUTHENTICATION_METHOD
        ] = GoogleOAuthAuthenticationMethod.OAUTH_INTERACTIVE.value

        credential_info = CredentialBase(
            credential_json=credential_dict,
            admin_public=True,
            source=DocumentSource.GOOGLE_DRIVE,
            name="OAuth (interactive)",
        )

        create_credential(credential_info, user, db_session)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"An error occurred during Google Drive OAuth: {str(e)}",
            },
        )
    finally:
        r.delete(r_key)

    # return the result
    return JSONResponse(
        content={
            "success": True,
            "message": "Google Drive OAuth completed successfully.",
            "redirect_on_success": session.redirect_on_success,
        }
    )
