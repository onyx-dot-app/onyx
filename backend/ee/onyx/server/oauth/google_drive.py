import base64
import json
import uuid
from typing import Any
from typing import cast

import requests
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.server.oauth.api_router import router
from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.app_configs import OAUTH_GOOGLE_DRIVE_CLIENT_ID
from onyx.configs.app_configs import OAUTH_GOOGLE_DRIVE_CLIENT_SECRET
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
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CredentialBase
from shared_configs.contextvars import get_current_tenant_id


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

    # SCOPE is per https://docs.danswer.dev/connectors/google-drive
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


@router.post("/connector/google-drive/callback")
def handle_google_drive_oauth_callback(
    code: str,
    state: str,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> JSONResponse:
    if not GoogleDriveOAuth.CLIENT_ID or not GoogleDriveOAuth.CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google Drive client ID or client secret is not configured.",
        )

    r = get_redis_client(tenant_id=tenant_id)

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
    try:
        session = GoogleDriveOAuth.parse_session(session_json)

        if not DEV_MODE:
            redirect_uri = GoogleDriveOAuth.REDIRECT_URI
        else:
            redirect_uri = GoogleDriveOAuth.DEV_REDIRECT_URI

        # Exchange the authorization code for an access token
        response = requests.post(
            GoogleDriveOAuth.TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": GoogleDriveOAuth.CLIENT_ID,
                "client_secret": GoogleDriveOAuth.CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
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
        credential_dict[DB_CREDENTIALS_AUTHENTICATION_METHOD] = (
            GoogleOAuthAuthenticationMethod.OAUTH_INTERACTIVE.value
        )

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
            "finalize_url": None,
            "redirect_on_success": session.redirect_on_success,
        }
    )
