import base64
import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast

import requests
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ee.onyx.server.oauth.api_router import router
from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
from onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.utils import CONFLUENCE_OAUTH_TOKEN_URL
from onyx.db.credentials import create_credential
from onyx.db.credentials import fetch_credential_by_id_for_user
from onyx.db.credentials import update_credential_json
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class ConfluenceCloudOAuth:
    # https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/

    class OAuthSession(BaseModel):
        """Stored in redis to be looked up on callback"""

        email: str
        redirect_on_success: str | None  # Where to send the user if OAuth flow succeeds

    class TokenResponse(BaseModel):
        access_token: str
        expires_in: int
        token_type: str
        refresh_token: str
        scope: str

    class AccessibleResources(BaseModel):
        id: str
        name: str
        url: str
        scopes: list[str]
        avatarUrl: str

    CLIENT_ID = OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
    CLIENT_SECRET = OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET
    TOKEN_URL = CONFLUENCE_OAUTH_TOKEN_URL

    ACCESSIBLE_RESOURCE_URL = (
        "https://api.atlassian.com/oauth/token/accessible-resources"
    )

    # All read scopes per https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3LO-and-forge-apps/
    CONFLUENCE_OAUTH_SCOPE = (
        # classic scope
        "read:confluence-space.summary%20"
        "read:confluence-props%20"
        "read:confluence-content.all%20"
        "read:confluence-content.summary%20"
        "read:confluence-content.permission%20"
        "read:confluence-user%20"
        "read:confluence-groups%20"
        "readonly:content.attachment:confluence%20"
        "search:confluence%20"
        # granular scope
        "read:attachment:confluence%20"  # possibly unneeded unless calling v2 attachments api
        "read:content-details:confluence%20"  # for permission sync
        "offline_access"
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
        # https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/#1--direct-the-user-to-the-authorization-url-to-get-an-authorization-code

        url = (
            "https://auth.atlassian.com/authorize"
            f"?audience=api.atlassian.com"
            f"&client_id={cls.CLIENT_ID}"
            f"&scope={cls.CONFLUENCE_OAUTH_SCOPE}"
            f"&redirect_uri={redirect_uri}"
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
    def parse_session(cls, session_json: str) -> OAuthSession:
        session = ConfluenceCloudOAuth.OAuthSession.model_validate_json(session_json)
        return session

    @classmethod
    def generate_finalize_url(cls, credential_id: int) -> str:
        return f"{WEB_DOMAIN}/admin/connectors/confluence/oauth/finalize?credential={credential_id}"


@router.post("/connector/confluence/callback")
def confluence_oauth_callback(
    code: str,
    state: str,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> JSONResponse:
    """Handles the backend logic for the frontend page that the user is redirected to
    after visiting the oauth authorization url."""

    if not ConfluenceCloudOAuth.CLIENT_ID or not ConfluenceCloudOAuth.CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Confluence Cloud client ID or client secret is not configured.",
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
            detail=f"Confluence Cloud OAuth failed - OAuth state key not found: key={r_key}",
        )

    session_json = session_json_bytes.decode("utf-8")
    try:
        session = ConfluenceCloudOAuth.parse_session(session_json)

        if not DEV_MODE:
            redirect_uri = ConfluenceCloudOAuth.REDIRECT_URI
        else:
            redirect_uri = ConfluenceCloudOAuth.DEV_REDIRECT_URI

        # Exchange the authorization code for an access token
        response = requests.post(
            ConfluenceCloudOAuth.TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": ConfluenceCloudOAuth.CLIENT_ID,
                "client_secret": ConfluenceCloudOAuth.CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

        token_response: ConfluenceCloudOAuth.TokenResponse | None = None

        try:
            token_response = ConfluenceCloudOAuth.TokenResponse.model_validate_json(
                response.text
            )
        except Exception:
            raise RuntimeError(
                "Confluence Cloud OAuth failed during code/token exchange."
            )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=token_response.expires_in)

        credential_info = CredentialBase(
            credential_json={
                "confluence_access_token": token_response.access_token,
                "confluence_refresh_token": token_response.refresh_token,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "expires_in": token_response.expires_in,
                "scope": token_response.scope,
            },
            admin_public=True,
            source=DocumentSource.CONFLUENCE,
            name="Confluence Cloud OAuth",
        )

        credential = create_credential(credential_info, user, db_session)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"An error occurred during Confluence Cloud OAuth: {str(e)}",
            },
        )
    finally:
        r.delete(r_key)

    # return the result
    return JSONResponse(
        content={
            "success": True,
            "message": "Confluence Cloud OAuth completed successfully.",
            "finalize_url": ConfluenceCloudOAuth.generate_finalize_url(credential.id),
            "redirect_on_success": session.redirect_on_success,
        }
    )


@router.get("/connector/confluence/accessible-resources")
def confluence_oauth_accessible_resources(
    credential_id: int,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> JSONResponse:
    """Atlassian's API is weird and does not supply us with enough info to be in a
    usable state after authorizing.  All API's require a cloud id. We have to list
    the accessible resources/sites and let the user choose which site to use."""

    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if not credential:
        raise HTTPException(400, f"Credential {credential_id} not found.")

    credential_dict = credential.credential_json
    access_token = credential_dict["confluence_access_token"]

    try:
        # Exchange the authorization code for an access token
        response = requests.get(
            ConfluenceCloudOAuth.ACCESSIBLE_RESOURCE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

        response.raise_for_status()
        accessible_resources_data = response.json()

        # Validate the list of AccessibleResources
        try:
            accessible_resources = [
                ConfluenceCloudOAuth.AccessibleResources(**resource)
                for resource in accessible_resources_data
            ]
        except ValidationError as e:
            raise RuntimeError(f"Failed to parse accessible resources: {e}")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"An error occurred retrieving Confluence Cloud accessible resources: {str(e)}",
            },
        )

    # return the result
    return JSONResponse(
        content={
            "success": True,
            "message": "Confluence Cloud get accessible resources completed successfully.",
            "accessible_resources": [
                resource.model_dump() for resource in accessible_resources
            ],
        }
    )


@router.post("/connector/confluence/finalize")
def confluence_oauth_finalize(
    credential_id: int,
    cloud_id: str,
    cloud_name: str,
    cloud_url: str,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> JSONResponse:
    """Saves the info for the selected cloud site to the credential.
    This is the final step in the confluence oauth flow where after the traditional
    OAuth process, the user has to select a site to associate with the credentials.
    After this, the credential is usable."""

    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if not credential:
        raise HTTPException(
            status_code=400,
            detail=f"Confluence Cloud OAuth failed - credential {credential_id} not found.",
        )

    new_credential_json: dict[str, Any] = dict(credential.credential_json)
    new_credential_json["cloud_id"] = cloud_id
    new_credential_json["cloud_name"] = cloud_name
    new_credential_json["wiki_base"] = cloud_url

    try:
        update_credential_json(credential_id, new_credential_json, user, db_session)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"An error occurred during Confluence Cloud OAuth: {str(e)}",
            },
        )

    # return the result
    return JSONResponse(
        content={
            "success": True,
            "message": "Confluence Cloud OAuth finalized successfully.",
            "redirect_url": f"{WEB_DOMAIN}/admin/connectors/confluence",
        }
    )
