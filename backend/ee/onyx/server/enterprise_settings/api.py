import hashlib
from datetime import datetime
from datetime import timezone
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi import status
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from ee.onyx.server.enterprise_settings.models import AnalyticsScriptUpload
from ee.onyx.server.enterprise_settings.models import EnterpriseSettings
from ee.onyx.server.enterprise_settings.store import get_logo_filename
from ee.onyx.server.enterprise_settings.store import get_logotype_filename
from ee.onyx.server.enterprise_settings.store import load_analytics_script
from ee.onyx.server.enterprise_settings.store import load_settings
from ee.onyx.server.enterprise_settings.store import store_analytics_script
from ee.onyx.server.enterprise_settings.store import store_settings
from ee.onyx.server.enterprise_settings.store import upload_logo
from ee.onyx.server.scim.auth import generate_scim_token
from ee.onyx.server.scim.models import ScimTokenCreate
from ee.onyx.server.scim.models import ScimTokenCreatedResponse
from ee.onyx.server.scim.models import ScimTokenResponse
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user_with_expired_token
from onyx.auth.users import get_user_manager
from onyx.auth.users import UserManager
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id

admin_router = APIRouter(prefix="/admin/enterprise-settings")
basic_router = APIRouter(prefix="/enterprise-settings")

logger = setup_logger()


class RefreshTokenData(BaseModel):
    access_token: str
    refresh_token: str
    session: dict = Field(..., description="Contains session information")
    userinfo: dict = Field(..., description="Contains user information")

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if "exp" not in self.session:
            raise ValueError("'exp' must be set in the session dictionary")
        if "userId" not in self.userinfo or "email" not in self.userinfo:
            raise ValueError(
                "'userId' and 'email' must be set in the userinfo dictionary"
            )


@basic_router.post("/refresh-token")
async def refresh_access_token(
    refresh_token: RefreshTokenData,
    user: User = Depends(current_user_with_expired_token),
    user_manager: UserManager = Depends(get_user_manager),
) -> None:
    try:
        logger.debug(f"Received response from Meechum auth URL for user {user.id}")

        # Extract new tokens
        new_access_token = refresh_token.access_token
        new_refresh_token = refresh_token.refresh_token

        new_expiry = datetime.fromtimestamp(
            refresh_token.session["exp"] / 1000, tz=timezone.utc
        )
        expires_at_timestamp = int(new_expiry.timestamp())

        logger.debug(f"Access token has been refreshed for user {user.id}")

        await user_manager.oauth_callback(
            oauth_name="custom",
            access_token=new_access_token,
            account_id=refresh_token.userinfo["userId"],
            account_email=refresh_token.userinfo["email"],
            expires_at=expires_at_timestamp,
            refresh_token=new_refresh_token,
            associate_by_email=True,
        )

        logger.info(f"Successfully refreshed tokens for user {user.id}")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.warning(f"Full authentication required for user {user.id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Full authentication required",
            )
        logger.error(
            f"HTTP error occurred while refreshing token for user {user.id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh token",
        )
    except Exception as e:
        logger.error(
            f"Unexpected error occurred while refreshing token for user {user.id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred",
        )


@admin_router.put("")
def admin_ee_put_settings(
    settings: EnterpriseSettings, _: User = Depends(current_admin_user)
) -> None:
    store_settings(settings)


@basic_router.get("")
def ee_fetch_settings() -> EnterpriseSettings:
    if MULTI_TENANT:
        tenant_id = get_current_tenant_id()
        if not tenant_id or tenant_id == POSTGRES_DEFAULT_SCHEMA:
            raise BasicAuthenticationError(detail="User must authenticate")

    return load_settings()


@admin_router.put("/logo")
def put_logo(
    file: UploadFile,
    is_logotype: bool = False,
    _: User = Depends(current_admin_user),
) -> None:
    upload_logo(file=file, is_logotype=is_logotype)


def _fetch_image_helper(request: Request, filename: str, label: str) -> Response:
    try:
        file_store = get_default_file_store()
        onyx_file = file_store.get_file_with_mime_type(filename)
    except Exception:
        logger.exception("Failed to fetch %s file", label)
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, f"Failed to fetch {label} file")

    if not onyx_file:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"No {label} file found")

    etag_value = f'"{hashlib.md5(onyx_file.data, usedforsecurity=False).hexdigest()}"'
    if_none_match = request.headers.get("if-none-match", "")
    # Strip W/ prefix for weak comparison per RFC 9110 §13.1.2
    client_etags = [
        tag.strip().removeprefix("W/")
        for tag in if_none_match.split(",")
        if tag.strip()
    ]
    normalized_etag = etag_value.removeprefix("W/")
    cache_headers = {
        "ETag": etag_value,
        "Cache-Control": "private, max-age=3600, must-revalidate",
    }
    if "*" in client_etags or normalized_etag in client_etags:
        return Response(status_code=304, headers=cache_headers)

    return Response(
        content=onyx_file.data,
        media_type=onyx_file.mime_type,
        headers=cache_headers,
    )


def fetch_logo_helper(request: Request) -> Response:
    return _fetch_image_helper(request, get_logo_filename(), "logo")


def fetch_logotype_helper(request: Request) -> Response:
    return _fetch_image_helper(request, get_logotype_filename(), "logotype")


@basic_router.get("/logotype")
def fetch_logotype(request: Request) -> Response:
    return fetch_logotype_helper(request)


@basic_router.get("/logo")
def fetch_logo(
    request: Request,
    is_logotype: bool = False,
) -> Response:
    if is_logotype:
        return fetch_logotype_helper(request)

    return fetch_logo_helper(request)


@admin_router.put("/custom-analytics-script")
def upload_custom_analytics_script(
    script_upload: AnalyticsScriptUpload, _: User = Depends(current_admin_user)
) -> None:
    try:
        store_analytics_script(script_upload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@basic_router.get("/custom-analytics-script")
def fetch_custom_analytics_script() -> str | None:
    return load_analytics_script()


# ---------------------------------------------------------------------------
# SCIM token management
# ---------------------------------------------------------------------------


def _get_scim_dal(db_session: Session = Depends(get_session)) -> ScimDAL:
    return ScimDAL(db_session)


@admin_router.get("/scim/token")
def get_active_scim_token(
    _: User = Depends(current_admin_user),
    dal: ScimDAL = Depends(_get_scim_dal),
) -> ScimTokenResponse:
    """Return the currently active SCIM token's metadata, or 404 if none."""
    token = dal.get_active_token()
    if not token:
        raise HTTPException(status_code=404, detail="No active SCIM token")

    # Derive the IdP domain from the first synced user as a heuristic.
    idp_domain: str | None = None
    mappings, _total = dal.list_user_mappings(start_index=1, count=1)
    if mappings:
        user = dal.get_user(mappings[0].user_id)
        if user and "@" in user.email:
            idp_domain = user.email.rsplit("@", 1)[1]

    return ScimTokenResponse(
        id=token.id,
        name=token.name,
        token_display=token.token_display,
        is_active=token.is_active,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        idp_domain=idp_domain,
    )


@admin_router.post("/scim/token", status_code=201)
def create_scim_token(
    body: ScimTokenCreate,
    user: User = Depends(current_admin_user),
    dal: ScimDAL = Depends(_get_scim_dal),
) -> ScimTokenCreatedResponse:
    """Create a new SCIM bearer token.

    Only one token is active at a time — creating a new token automatically
    revokes all previous tokens. The raw token value is returned exactly once
    in the response; it cannot be retrieved again.
    """
    raw_token, hashed_token, token_display = generate_scim_token()
    token = dal.create_token(
        name=body.name,
        hashed_token=hashed_token,
        token_display=token_display,
        created_by_id=user.id,
    )
    dal.commit()

    return ScimTokenCreatedResponse(
        id=token.id,
        name=token.name,
        token_display=token.token_display,
        is_active=token.is_active,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        raw_token=raw_token,
    )
