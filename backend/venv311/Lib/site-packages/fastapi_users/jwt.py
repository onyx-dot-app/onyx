from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pydantic import SecretStr

SecretType = str | SecretStr
JWT_ALGORITHM = "HS256"


def _get_secret_value(secret: SecretType) -> str:
    if isinstance(secret, SecretStr):
        return secret.get_secret_value()
    return secret


def generate_jwt(
    data: dict,
    secret: SecretType,
    lifetime_seconds: int | None = None,
    algorithm: str = JWT_ALGORITHM,
) -> str:
    payload = data.copy()
    if lifetime_seconds:
        expire = datetime.now(timezone.utc) + timedelta(seconds=lifetime_seconds)
        payload["exp"] = expire
    return jwt.encode(payload, _get_secret_value(secret), algorithm=algorithm)


def decode_jwt(
    encoded_jwt: str,
    secret: SecretType,
    audience: list[str],
    algorithms: list[str] = [JWT_ALGORITHM],
) -> dict[str, Any]:
    return jwt.decode(
        encoded_jwt,
        _get_secret_value(secret),
        audience=audience,
        algorithms=algorithms,
    )
