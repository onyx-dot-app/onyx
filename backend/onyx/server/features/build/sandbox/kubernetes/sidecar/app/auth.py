from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_bearer_token(
    authorization: str | None = Header(default=None),
) -> None:
    """Constant-time bearer-token check.

    Raises 401 on missing/malformed/incorrect headers. Raises 503 if the
    configured token source is transiently unavailable (e.g. mounted Secret file
    disappears during a rotation) so callers see a retryable error instead of an
    opaque 500. Constant-time comparison avoids timing-based token leakage.
    """
    try:
        expected = get_settings().load_auth_token()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth token source is temporarily unavailable",
            headers={"Retry-After": "1"},
        ) from exc

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
