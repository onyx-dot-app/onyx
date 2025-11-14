from datetime import datetime
from functools import lru_cache

import jwt
import requests
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from jwt import decode as jwt_decode
from jwt import InvalidTokenError
from jwt import PyJWTError
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ee.onyx.configs.app_configs import JWT_PUBLIC_KEY_URL
from ee.onyx.configs.app_configs import SUPER_CLOUD_API_KEY
from ee.onyx.configs.app_configs import SUPER_USERS
from ee.onyx.db.saml import get_saml_account
from ee.onyx.server.seeding import get_seed_config
from ee.onyx.utils.secrets import extract_hashed_cookie
from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.constants import AuthType
from onyx.db.models import User
from onyx.utils.logger import setup_logger


logger = setup_logger()


@lru_cache()
def get_public_key() -> str | None:
    if not JWT_PUBLIC_KEY_URL:
        logger.error("URL для публичного ключа JWT (JWT_PUBLIC_KEY_URL) не задан.")
        return None

    try:
        resp = requests.get(JWT_PUBLIC_KEY_URL)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.error(f"Ошибка при получении публичного ключа: {e}")
        return None


async def verify_jwt_token(token: str, async_db_session: AsyncSession) -> User | None:
    pub_key = get_public_key()
    if not pub_key:
        logger.error("Не удалось получить публичный ключ для проверки токена.")
        return None

    try:
        token_data = jwt_decode(
            token,
            pub_key,
            algorithms=["RS256"],
            audience=None,
        )

        user_email = token_data.get("email")
        if not user_email:
            return None

        # Поиск пользователя в БД по email (регистронезависимый)
        stmt = select(User).where(func.lower(User.email) == func.lower(user_email))
        result = await async_db_session.execute(stmt)
        return result.scalars().first()

    except InvalidTokenError:
        logger.error("Обнаружен невалидный JWT токен.")
        get_public_key.cache_clear()
    except PyJWTError as jwt_err:
        logger.error(f"Ошибка декодирования JWT: {jwt_err}")
        get_public_key.cache_clear()

    return None


def verify_auth_setting() -> None:
    # поддерживаются все потоки аутентификации
    logger.notice(f"Текущий тип аутентификации: {AUTH_TYPE.value}")


async def optional_user_(
    request: Request,
    user: User | None,
    async_db_session: AsyncSession,
) -> User | None:
    # 1. Попытка аутентификации через SAML cookie
    if AUTH_TYPE == AuthType.SAML:
        if cookie_val := extract_hashed_cookie(request):
            saml_acc = await get_saml_account(
                cookie=cookie_val,
                async_db_session=async_db_session
            )
            if saml_acc:
                user = saml_acc.user

    # 2. Если пользователь не найден, проверяем JWT в заголовках
    if not user and JWT_PUBLIC_KEY_URL:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ", 1)[1].strip()
            user = await verify_jwt_token(jwt_token, async_db_session)

    return user


def get_default_admin_user_emails_() -> list[str]:
    seed_conf = get_seed_config()
    # Возвращаем список админов из конфигурации, если он есть
    if seed_conf and seed_conf.admin_user_emails:
        return seed_conf.admin_user_emails
    return []


async def current_cloud_superuser(
    request: Request,
    user: User | None = Depends(current_admin_user),
) -> User | None:
    # Извлекаем API ключ, убирая префикс Bearer, если он есть
    raw_header = request.headers.get("Authorization", "")
    api_key = raw_header.replace("Bearer ", "")

    if api_key != SUPER_CLOUD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Проверка прав: пользователь должен быть в списке супер-юзеров
    is_superuser = user and user.email in SUPER_USERS
    if not is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. User must be a cloud superuser to perform this action.",
        )

    return user


def generate_anonymous_user_jwt_token(tenant_id: str) -> str:
    claims = {
        "tenant_id": tenant_id,
        # Токен бессрочный
        "iat": datetime.utcnow(),
    }
    return jwt.encode(claims, USER_AUTH_SECRET, algorithm="HS256")


def decode_anonymous_user_jwt_token(token: str) -> dict:
    return jwt.decode(token, USER_AUTH_SECRET, algorithms=["HS256"])
