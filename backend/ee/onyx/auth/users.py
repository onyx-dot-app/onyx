import json
from datetime import datetime
from functools import lru_cache
from typing import Any

import jwt
import requests
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from jwt import decode as jwt_decode
from jwt import InvalidTokenError
from jwt import PyJWTError
from jwt.algorithms import RSAAlgorithm
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
def get_public_key() -> tuple[str | dict[str, Any], str] | None:
    """Fetch and cache JWT verification material from either a PEM endpoint or a JWKS."""
    if JWT_PUBLIC_KEY_URL is None:
        logger.error("JWT_PUBLIC_KEY_URL is not set")
        return None

    try:
        response = requests.get(JWT_PUBLIC_KEY_URL)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f"Failed to fetch JWT public key: {str(exc)}")
        return None
    content_type = response.headers.get("Content-Type", "").lower()
    raw_body = response.text
    body_lstripped = raw_body.lstrip()

    if "application/json" in content_type or body_lstripped.startswith("{"):
        try:
            data = response.json()
        except ValueError:
            logger.error("JWT public key URL returned invalid JSON")
            return None

        if isinstance(data, dict) and "keys" in data:
            return data, "jwks"

        logger.error(
            "JWT public key URL returned JSON but no JWKS 'keys' field was found"
        )
        return None

    body = raw_body.strip()
    if not body:
        logger.error("JWT public key URL returned an empty response")
        return None

    return body, "pem"


def _resolve_public_key_from_jwks(
    token: str, jwks_payload: dict[str, Any]
) -> Any | None:
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as e:
        logger.error(f"Unable to parse JWT header: {str(e)}")
        return None

    keys = jwks_payload.get("keys", []) if isinstance(jwks_payload, dict) else []
    if not keys:
        logger.error("JWKS payload did not contain any keys")
        return None

    kid = header.get("kid")
    thumbprint = header.get("x5t")

    candidates = []
    if kid:
        candidates = [k for k in keys if k.get("kid") == kid]
    if not candidates and thumbprint:
        candidates = [k for k in keys if k.get("x5t") == thumbprint]

    if not candidates:
        logger.warning("No matching JWK found for token header kid=%s", kid)
        return None

    if len(candidates) > 1:
        logger.warning(
            "Multiple JWKs matched token header kid=%s; selecting the first occurrence",
            kid,
        )

    jwk = candidates[0]
    try:
        return RSAAlgorithm.from_jwk(json.dumps(jwk))
    except ValueError as e:
        logger.error(f"Failed to construct RSA key from JWK: {str(e)}")
        return None


async def verify_jwt_token(token: str, async_db_session: AsyncSession) -> User | None:
    for attempt in range(2):
        public_key_payload = get_public_key()
        if public_key_payload is None:
            logger.error("Failed to retrieve public key")
            return None

        key_material, key_format = public_key_payload

        if key_format == "jwks":
            public_key = _resolve_public_key_from_jwks(
                token, key_material  # type: ignore[arg-type]
            )
        else:
            public_key = key_material

        if public_key is None:
            if attempt == 0:
                get_public_key.cache_clear()
                continue

            logger.error("Unable to resolve a public key for JWT verification")
            return None

        try:
            payload = jwt_decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except InvalidTokenError as e:
            logger.error(f"Invalid JWT token: {str(e)}")
            if attempt == 0:
                get_public_key.cache_clear()
                continue
            return None
        except PyJWTError as e:
            logger.error(f"JWT decoding error: {str(e)}")
            if attempt == 0:
                get_public_key.cache_clear()
                continue
            return None

        email = payload.get("email")
        if email:
            result = await async_db_session.execute(
                select(User).where(func.lower(User.email) == func.lower(email))
            )
            return result.scalars().first()

    return None


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

    # If user is still None, check for JWT in Authorization header
    if user is None and JWT_PUBLIC_KEY_URL is not None:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :].strip()
            user = await verify_jwt_token(token, async_db_session)

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


def generate_anonymous_user_jwt_token(tenant_id: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        # Token does not expire
        "iat": datetime.utcnow(),  # Issued at time
    }

    return jwt.encode(payload, USER_AUTH_SECRET, algorithm="HS256")


def decode_anonymous_user_jwt_token(token: str) -> dict:
    return jwt.decode(token, USER_AUTH_SECRET, algorithms=["HS256"])
