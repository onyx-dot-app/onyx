"""SCIM bearer token authentication.

SCIM endpoints are authenticated via bearer tokens that admins create in the
Onyx UI. This module provides:

  - ``verify_scim_token``: FastAPI dependency that extracts, hashes, and
    validates the token from the Authorization header.
  - ``generate_scim_token``: Creates a new cryptographically random token
    and returns the raw value, its SHA-256 hash, and a display suffix.

Token format: ``onyx_scim_<random>`` where ``<random>`` is 48 bytes of
URL-safe base64 from ``secrets.token_urlsafe``. Under multi-tenancy the
tenant is embedded as ``onyx_scim_<tenant>.<random>``, matching API keys and
PATs — see ``generate_scim_token``.

The hash is stored in the ``scim_token`` table; the raw value is shown to
the admin exactly once at creation time.
"""

import hashlib
import secrets
from urllib.parse import quote

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from onyx.auth.constants import SCIM_TOKEN_LENGTH, SCIM_TOKEN_PREFIX
from onyx.auth.utils import get_hashed_bearer_token_from_request
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ScimToken
from shared_configs.configs import MULTI_TENANT


class ScimAuthError(Exception):
    """Raised when SCIM bearer token authentication fails.

    Unlike HTTPException, this carries the status and detail so the SCIM
    exception handler can wrap them in an RFC 7644 §3.12 error envelope
    with ``schemas`` and ``status`` fields.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _hash_scim_token(token: str) -> str:
    """SHA-256 hash a SCIM token. No salt needed — tokens are random."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_scim_token(tenant_id: str | None = None) -> tuple[str, str, str]:
    """Generate a new SCIM bearer token.

    Under multi-tenancy the tenant is embedded in the token as
    ``onyx_scim_<tenant>.<random>``, the same shape API keys and PATs use
    (``generate_api_key``). An IdP presents only this bearer token, so the
    tenant-tracking middleware has nothing else to resolve the workspace
    from; without it every SCIM request falls back to the default schema.

    Returns:
        A tuple of ``(raw_token, hashed_token, token_display)`` where
        ``token_display`` is a masked version showing only the last 4 chars.
    """
    if not MULTI_TENANT or not tenant_id:
        raw_token = SCIM_TOKEN_PREFIX + secrets.token_urlsafe(SCIM_TOKEN_LENGTH)
    else:
        encoded_tenant = quote(tenant_id)
        raw_token = (
            f"{SCIM_TOKEN_PREFIX}{encoded_tenant}."
            f"{secrets.token_urlsafe(SCIM_TOKEN_LENGTH)}"
        )

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
        raise ScimAuthError(401, "Missing or invalid SCIM bearer token")

    token = dal.get_token_by_hash(hashed)

    if not token:
        raise ScimAuthError(401, "Invalid SCIM bearer token")

    if not token.is_active:
        raise ScimAuthError(401, "SCIM token has been revoked")

    return token
