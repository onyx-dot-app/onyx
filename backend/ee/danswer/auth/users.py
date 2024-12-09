from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from danswer.auth.users import current_admin_user
from danswer.configs.app_configs import AUTH_TYPE
from danswer.configs.app_configs import SUPER_CLOUD_API_KEY
from danswer.configs.app_configs import SUPER_USERS
from danswer.configs.constants import AuthType
from danswer.db.models import User
from danswer.utils.logger import setup_logger
from ee.danswer.db.saml import get_saml_account
from ee.danswer.server.seeding import get_seed_config
from ee.danswer.utils.secrets import extract_hashed_cookie

logger = setup_logger()


def verify_auth_setting() -> None:
    # All the Auth flows are valid for EE version
    logger.notice(f"Using Auth Type: {AUTH_TYPE.value}")


async def optional_user_(
    request: Request,
    user: User | None,
    async_db_session: AsyncSession,
) -> User | None:
    # Check if the user has a session cookie from SAML
    if AUTH_TYPE == AuthType.SAML:
        saved_cookie = extract_hashed_cookie(request)

        if saved_cookie:
            saml_account = await get_saml_account(
                cookie=saved_cookie, async_db_session=async_db_session
            )
            user = saml_account.user if saml_account else None

    return user


def get_default_admin_user_emails_() -> list[str]:
    seed_config = get_seed_config()
    if seed_config and seed_config.admin_user_emails:
        return seed_config.admin_user_emails
    return []


async def current_cloud_superuser(
    request: Request,
    user: User | None = Depends(current_admin_user),
) -> User | None:
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if api_key != SUPER_CLOUD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if user and user.email not in SUPER_USERS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. User must be a cloud superuser to perform this action.",
        )
    return user
