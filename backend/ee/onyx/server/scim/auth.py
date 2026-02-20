"""SCIM bearer token authentication.

SCIM endpoints are authenticated via bearer tokens that admins create in the
Onyx UI. This module provides:

  - ``verify_scim_token``: FastAPI dependency that extracts, hashes, and
    validates the token from the Authorization header.
  - ``generate_scim_token``: Creates a new cryptographically random token
    and returns the raw value, its SHA-256 hash, and a display suffix.

Token format: ``onyx_scim_<random>`` where ``<random>`` is 48 bytes of
URL-safe base64 from ``secrets.token_urlsafe``.

The hash is stored in the ``scim_token`` table; the raw value is shown to
the admin exactly once at creation time.
"""

import hashlib
import secrets

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from onyx.auth.utils import get_hashed_bearer_token_from_request
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ScimToken

SCIM_TOKEN_PREFIX = "onyx_scim_"
SCIM_TOKEN_LENGTH = 48


def _hash_scim_token(token: str) -> str:
    """SHA-256 hash a SCIM token. No salt needed — tokens are random."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_scim_token() -> tuple[str, str, str]:
    """Generate a new SCIM bearer token.

    Returns:
        A tuple of ``(raw_token, hashed_token, token_display)`` where
        ``token_display`` is a masked version showing only the last 4 chars.
    """
    raw_token = SCIM_TOKEN_PREFIX + secrets.token_urlsafe(SCIM_TOKEN_LENGTH)
    hashed_token = _hash_scim_token(raw_token)
    token_display = SCIM_TOKEN_PREFIX + "****" + raw_token[-4:]
    return raw_token, hashed_token, token_display


def _get_hashed_scim_token_from_request(request: Request) -> str | None:
    """Extract and hash a SCIM token from the request Authorization header."""
    return get_hashed_bearer_token_from_request(
        request,
        valid_prefixes=[SCIM_TOKEN_PREFIX],
        hash_fn=_hash_scim_token,
    )


def _get_scim_dal(db_session: Session = Depends(get_session)) -> ScimDAL:
    return ScimDAL(db_session)


def verify_scim_token(
    request: Request,
    dal: ScimDAL = Depends(_get_scim_dal),
) -> ScimToken:
    """FastAPI dependency that authenticates SCIM requests.

    Extracts the bearer token from the Authorization header, hashes it,
    looks it up in the database, and verifies it is active.

    Note:
        This dependency does NOT update ``last_used_at`` — the endpoint
        should do that via ``ScimDAL.update_token_last_used()`` so the
        timestamp write is part of the endpoint's transaction.

    Raises:
        HTTPException(401): If the token is missing, invalid, or inactive.
    """
    hashed = _get_hashed_scim_token_from_request(request)
    if not hashed:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid SCIM bearer token",
        )

    token = dal.get_token_by_hash(hashed)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid SCIM bearer token",
        )

    if not token.is_active:
        raise HTTPException(
            status_code=401,
            detail="SCIM token has been revoked",
        )

    return token
