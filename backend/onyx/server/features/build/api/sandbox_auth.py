"""Authentication dependency for sandbox-callable build endpoints.

Endpoints under ``/api/build/sandbox/*`` are reached from inside a Craft
sandbox, not from a browser. They authenticate via a bearer token that was
minted at session creation and injected into the sandbox's environment as
``ONYX_BUILD_SESSION_TOKEN``. The sandbox also forwards the tenant id via the
standard ``X-Onyx-Tenant-ID`` header (handled by ``add_onyx_tenant_id_middleware``
upstream of this dependency, so the tenant context is already set on the
request).
"""

from dataclasses import dataclass

from fastapi import Depends
from fastapi import Header
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session
from onyx.db.models import BuildSession
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.build_session import (
    get_build_session_by_sandbox_token,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


_BEARER_PREFIX = "Bearer "


@dataclass
class SandboxRequestContext:
    """Resolved identity for a sandbox-issued request."""

    build_session: BuildSession
    user: User


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, "Missing Authorization header")
    if not authorization.startswith(_BEARER_PREFIX):
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED, "Authorization header must use Bearer scheme"
        )
    token = authorization[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, "Empty bearer token")
    return token


def require_sandbox_session_token(
    authorization: str | None = Header(default=None),
    db_session: Session = Depends(get_session),
) -> SandboxRequestContext:
    """FastAPI dependency that resolves a sandbox bearer token to its session.

    Returns the underlying ``BuildSession`` and owning ``User`` so the endpoint
    can run downstream work as that user. Raises ``OnyxError(UNAUTHENTICATED)``
    if the token is missing, malformed, or unknown.

    Logs only a fingerprint of the token (first 6 chars + length) so the raw
    secret never leaves this process via the log pipeline.
    """
    token = _extract_bearer_token(authorization)
    fingerprint = f"{token[:6]}…(len={len(token)})"

    build_session = get_build_session_by_sandbox_token(token, db_session)
    if build_session is None:
        logger.info(f"Sandbox auth rejected unknown token: {fingerprint}")
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, "Invalid sandbox session token")

    user = build_session.user
    if user is None:
        # The user that owned this session was deleted; the session can't run
        # privileged work as a ghost. Treat as unauthenticated.
        logger.info(
            f"Sandbox auth rejected session {build_session.id} with no owner: {fingerprint}"
        )
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED, "Session owner is no longer active"
        )

    return SandboxRequestContext(build_session=build_session, user=user)
