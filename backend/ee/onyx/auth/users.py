from datetime import datetime

import jwt
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status

from ee.onyx.configs.app_configs import SUPER_CLOUD_API_KEY
from ee.onyx.configs.app_configs import SUPER_USERS
from ee.onyx.server.seeding import get_seed_config
from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.db.models import User
from onyx.utils.logger import setup_logger


logger = setup_logger()


def verify_auth_setting() -> None:
    # All the Auth flows are valid for EE version
    logger.notice(f"Using Auth Type: {AUTH_TYPE.value}")


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


def generate_anonymous_user_jwt_token(tenant_id: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        # Token does not expire
        "iat": datetime.utcnow(),  # Issued at time
    }

    return jwt.encode(payload, USER_AUTH_SECRET, algorithm="HS256")


def decode_anonymous_user_jwt_token(token: str) -> dict:
    return jwt.decode(token, USER_AUTH_SECRET, algorithms=["HS256"])
