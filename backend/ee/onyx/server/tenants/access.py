from datetime import datetime
from datetime import timedelta

import jwt
from fastapi import HTTPException
from fastapi import Request

from onyx.configs.app_configs import DATA_PLANE_SECRET
from onyx.configs.app_configs import EXPECTED_API_KEY
from onyx.configs.app_configs import JWT_ALGORITHM
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generate_data_plane_token() -> str:
    if DATA_PLANE_SECRET is None:
        raise ValueError("DATA_PLANE_SECRET is not set")

    payload = {
        "iss": "data_plane",
        "exp": datetime.utcnow() + timedelta(minutes=5),
        "iat": datetime.utcnow(),
        "scope": "api_access",
    }

    token = jwt.encode(payload, DATA_PLANE_SECRET, algorithm=JWT_ALGORITHM)
    return token


async def control_plane_dep(request: Request) -> None:
    api_key = request.headers.get("X-API-KEY")
    if api_key != EXPECTED_API_KEY:
        logger.warning("Invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("Invalid authorization header")
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, DATA_PLANE_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("scope") != "tenant:create":
            logger.warning("Insufficient permissions")
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        logger.warning("Invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")
