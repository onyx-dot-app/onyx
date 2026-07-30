"""Token-issuance seam for mobile auth.

A single indirection point for minting the credential a native client receives.
Today it mints the SAME session token the web cookie flow uses (via the active
strategy's ``write_token``) — server-revocable under the redis/postgres backends,
a self-contained non-revocable JWT under ``AUTH_BACKEND=jwt`` — differing from web
only in transport (Authorization header vs HttpOnly cookie).

This seam exists so a future access-token + refresh-token-rotation
implementation (RFC 9700) can swap the body here without touching any caller.
"""

from fastapi_users import models
from fastapi_users.authentication import Strategy


async def issue_session_credential(
    user: models.UP, strategy: Strategy[models.UP, models.ID]
) -> str:
    return await strategy.write_token(user)
