from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_bearer_token(
    authorization: str | None = Header(default=None),
) -> None:
    """Constant-time bearer-token check.

    Raises 401 on missing/malformed/incorrect headers. Constant-time comparison
    avoids timing-based token leakage.
    """
    expected = get_settings().load_auth_token()

    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
