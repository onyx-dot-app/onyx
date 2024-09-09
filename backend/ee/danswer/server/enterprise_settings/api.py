from datetime import datetime
from datetime import timedelta
from datetime import timezone

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from fastapi import status
from fastapi import UploadFile
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.auth.users import get_user_manager
from danswer.auth.users import UserManager
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.file_store.file_store import get_default_file_store
from danswer.utils.logger import setup_logger
from ee.danswer.server.enterprise_settings.models import AnalyticsScriptUpload
from ee.danswer.server.enterprise_settings.models import EnterpriseSettings
from ee.danswer.server.enterprise_settings.store import _LOGO_FILENAME
from ee.danswer.server.enterprise_settings.store import _LOGOTYPE_FILENAME
from ee.danswer.server.enterprise_settings.store import load_analytics_script
from ee.danswer.server.enterprise_settings.store import load_settings
from ee.danswer.server.enterprise_settings.store import store_analytics_script
from ee.danswer.server.enterprise_settings.store import store_settings
from ee.danswer.server.enterprise_settings.store import upload_logo
from shared_configs.configs import CUSTOM_REFRESH_URL

admin_router = APIRouter(prefix="/admin/enterprise-settings")
basic_router = APIRouter(prefix="/enterprise-settings")

logger = setup_logger()


def mocked_refresh_token() -> dict:
    """
    This function mocks the response from a token refresh endpoint.
    It generates a mock access token, refresh token, and user information
    with an expiration time set to 1 hour from now.
    This is useful for testing or development when the actual refresh endpoint is not available.
    """
    mock_exp = int((datetime.now() + timedelta(hours=1)).timestamp() * 1000)
    data = {
        "access_token": "asdf Mock access token",
        "refresh_token": "asdf Mock refresh token",
        "session": {"exp": mock_exp},
        "userinfo": {
            "sub": "Mock email",
            "familyName": "Mock name",
            "givenName": "Mock name",
            "fullName": "Mock name",
            "userId": "Mock User ID",
            "email": "test_email@danswer.ai",
        },
    }
    return data


@basic_router.get("/refresh-token")
async def refresh_access_token(
    user: User = Depends(current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> None:
    # return
    if CUSTOM_REFRESH_URL is None:
        logger.error(
            "Custom refresh URL is not set and client is attempting to custom refresh"
        )
        raise HTTPException(
            status_code=500,
            detail="Custom refresh URL is not set",
        )

    try:
        async with httpx.AsyncClient() as client:
            logger.debug(f"Sending request to custom refresh URL for user {user.id}")
            access_token = user.oauth_accounts[0].access_token

            response = await client.get(
                CUSTOM_REFRESH_URL,
                params={"info": "json", "access_token_refresh_interval": 3600},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()

            # NOTE: Here is where we can mock the response
            # data = mocked_refresh_token()

        logger.debug(f"Received response from Meechum auth URL for user {user.id}")

        # Extract new tokens
        new_access_token = data["access_token"]
        new_refresh_token = data["refresh_token"]

        new_expiry = datetime.fromtimestamp(
            data["session"]["exp"] / 1000, tz=timezone.utc
        )
        expires_at_timestamp = int(new_expiry.timestamp())

        logger.debug(f"Access token has been refreshed for user {user.id}")

        await user_manager.oauth_callback(
            oauth_name="custom",
            access_token=new_access_token,
            account_id=data["userinfo"]["userId"],
            account_email=data["userinfo"]["email"],
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
def put_settings(
    settings: EnterpriseSettings, _: User | None = Depends(current_admin_user)
) -> None:
    try:
        settings.check_validity()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store_settings(settings)


@basic_router.get("")
def fetch_settings() -> EnterpriseSettings:
    return load_settings()


@admin_router.put("/logo")
def put_logo(
    file: UploadFile,
    is_logotype: bool = False,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    upload_logo(file=file, db_session=db_session, is_logotype=is_logotype)


def fetch_logo_or_logotype(is_logotype: bool, db_session: Session) -> Response:
    try:
        file_store = get_default_file_store(db_session)
        filename = _LOGOTYPE_FILENAME if is_logotype else _LOGO_FILENAME
        file_io = file_store.read_file(filename, mode="b")
        # NOTE: specifying "image/jpeg" here, but it still works for pngs
        # TODO: do this properly
        return Response(content=file_io.read(), media_type="image/jpeg")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"No {'logotype' if is_logotype else 'logo'} file found",
        )


@basic_router.get("/logotype")
def fetch_logotype(db_session: Session = Depends(get_session)) -> Response:
    return fetch_logo_or_logotype(is_logotype=True, db_session=db_session)


@basic_router.get("/logo")
def fetch_logo(
    is_logotype: bool = False, db_session: Session = Depends(get_session)
) -> Response:
    return fetch_logo_or_logotype(is_logotype=is_logotype, db_session=db_session)


@admin_router.put("/custom-analytics-script")
def upload_custom_analytics_script(
    script_upload: AnalyticsScriptUpload, _: User | None = Depends(current_admin_user)
) -> None:
    try:
        store_analytics_script(script_upload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@basic_router.get("/custom-analytics-script")
def fetch_custom_analytics_script() -> str | None:
    return load_analytics_script()
