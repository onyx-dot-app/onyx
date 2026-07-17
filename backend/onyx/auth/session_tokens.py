"""Redis session-token value format and rejection classification.

Token values embed their logical expiry; the physical TTL adds a grace window
and logout writes a tombstone instead of deleting, so a rejected token can be
classified: EXPIRED (embedded expiry passed), TERMINATED (tombstone), NOT_FOUND
(no entry: cookie outlived the grace window, or Redis dropped the key),
MALFORMED (unparseable or sub-less value). Pre-upgrade values (sub present, no
issued_at) stay valid on bare key existence; their physical TTL is their
pre-upgrade logical expiry, so deploying this format signs nobody out.

``read_token`` must return None rather than raise (API keys/PATs/JWTs share the
bearer transport and legitimately miss in Redis), so the classification is
stashed in a request-scoped ContextVar and turned into a reasoned ``OnyxError``
only where authentication has conclusively failed for the request.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.auth.constants import API_KEY_PREFIX
from onyx.auth.constants import DEPRECATED_API_KEY_PREFIX
from onyx.auth.constants import PAT_PREFIX
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# How long an entry outlives its logical expiry (and how long a tombstone
# lingers); past this, rejections classify as NOT_FOUND.
SESSION_TOKEN_GRACE_PERIOD_SECONDS = 60 * 60


class SessionTokenValue(BaseModel):
    """
    JSON stored under ``fastapi_users_token:<token>``. All fields optional so
    legacy values and tombstones parse too; ``AwareDatetime`` rejects naive
    timestamps at parse time.
    """

    sub: str | None = None
    tenant_id: str | None = None
    issued_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    logged_out_at: AwareDatetime | None = None


class SessionRejectionReason(Enum):
    EXPIRED = "expired"
    TERMINATED = "terminated"
    NOT_FOUND = "not_found"
    MALFORMED = "malformed"


_REASON_TO_ERROR_CODE = {
    SessionRejectionReason.EXPIRED: OnyxErrorCode.SESSION_EXPIRED,
    SessionRejectionReason.TERMINATED: OnyxErrorCode.SESSION_TERMINATED,
    SessionRejectionReason.NOT_FOUND: OnyxErrorCode.SESSION_UNRECOGNIZED,
    SessionRejectionReason.MALFORMED: OnyxErrorCode.SESSION_UNRECOGNIZED,
}

_REASON_TO_DETAIL = {
    SessionRejectionReason.EXPIRED: "Session expired. Please log in again.",
    SessionRejectionReason.TERMINATED: "Session was signed out. Please log in again.",
    SessionRejectionReason.NOT_FOUND: "Session not recognized. Please log in again.",
    SessionRejectionReason.MALFORMED: "Session not recognized. Please log in again.",
}


@dataclass(frozen=True)
class SessionRejection:
    reason: SessionRejectionReason
    # None when nothing was stored or the value was unparseable.
    token_value: SessionTokenValue | None


_SESSION_REJECTION: ContextVar[SessionRejection | None] = ContextVar(
    "session_rejection", default=None
)


def build_session_token_value(
    *,
    user_id: str,
    tenant_id: str | None,
    issued_at: AwareDatetime,
    expires_at: AwareDatetime | None,
) -> str:
    return SessionTokenValue(
        sub=user_id,
        tenant_id=tenant_id,
        issued_at=issued_at,
        expires_at=expires_at,
    ).model_dump_json(exclude_none=True)


def build_session_tombstone_value(
    previous_raw_value: str | bytes | None, fallback_user_id: str
) -> str:
    """
    Builds the logout tombstone, preserving the original fields when the
    previous value parses.
    """
    previous: SessionTokenValue | None = None
    if previous_raw_value is not None:
        try:
            previous = SessionTokenValue.model_validate_json(previous_raw_value)
        except ValidationError:
            previous = None
    if previous is None:
        previous = SessionTokenValue(sub=fallback_user_id)
    return previous.model_copy(
        update={"logged_out_at": datetime.now(timezone.utc)}
    ).model_dump_json(exclude_none=True)


def compute_session_expires_at(
    issued_at: AwareDatetime, lifetime_seconds: int | None
) -> AwareDatetime | None:
    if lifetime_seconds is None:
        return None
    return issued_at + timedelta(seconds=lifetime_seconds)


def physical_session_ttl_seconds(lifetime_seconds: int | None) -> int | None:
    if lifetime_seconds is None:
        return None
    return lifetime_seconds + SESSION_TOKEN_GRACE_PERIOD_SECONDS


def may_be_session_token(token: str) -> bool:
    """
    Session tokens are bare ``token_urlsafe()`` strings: no prefix, no dots.
    Excludes API keys / PATs / JWTs so their expected misses never classify.
    """
    if token.startswith((API_KEY_PREFIX, DEPRECATED_API_KEY_PREFIX, PAT_PREFIX)):
        return False
    return "." not in token


def classify_session_token_value(
    raw_value: str | bytes | None,
) -> SessionTokenValue | SessionRejection:
    """Returns the parsed value if the session is live, else the rejection."""
    if raw_value is None:
        return SessionRejection(
            reason=SessionRejectionReason.NOT_FOUND, token_value=None
        )

    try:
        value = SessionTokenValue.model_validate_json(raw_value)
    except ValidationError:
        return SessionRejection(
            reason=SessionRejectionReason.MALFORMED, token_value=None
        )

    if value.logged_out_at is not None:
        return SessionRejection(
            reason=SessionRejectionReason.TERMINATED, token_value=value
        )
    if value.sub is None:
        return SessionRejection(
            reason=SessionRejectionReason.MALFORMED, token_value=value
        )
    # Pre-upgrade values (no issued_at / expires_at) fall through as valid:
    # their physical TTL is their pre-upgrade logical expiry.
    if value.expires_at is not None and value.expires_at <= datetime.now(timezone.utc):
        return SessionRejection(
            reason=SessionRejectionReason.EXPIRED, token_value=value
        )
    return value


def record_session_rejection(rejection: SessionRejection) -> None:
    """
    The first rejection backed by a stored value wins; a bare NOT_FOUND miss
    only fills a void.
    """
    existing = _SESSION_REJECTION.get()
    if existing is None or (
        existing.reason == SessionRejectionReason.NOT_FOUND
        and rejection.reason != SessionRejectionReason.NOT_FOUND
    ):
        _SESSION_REJECTION.set(rejection)


def get_session_rejection() -> SessionRejection | None:
    return _SESSION_REJECTION.get()


def build_session_rejection_error() -> OnyxError | None:
    """
    Turns the request's recorded rejection (if any) into a reasoned
    ``OnyxError``, logging the diagnostic WARNING.
    """
    rejection = _SESSION_REJECTION.get()
    if rejection is None:
        return None

    value = rejection.token_value
    token_age: timedelta | None = None
    if value is not None and value.issued_at is not None:
        token_age = datetime.now(timezone.utc) - value.issued_at

    logger.warning(
        "Rejected session token: reason=%s user_id=%s token_age=%s issued_at=%s "
        "expires_at=%s logged_out_at=%s",
        rejection.reason.value,
        value.sub if value else None,
        token_age,
        value.issued_at if value else None,
        value.expires_at if value else None,
        value.logged_out_at if value else None,
    )
    if rejection.reason == SessionRejectionReason.NOT_FOUND:
        logger.warning(
            "Presented session token has no Redis entry: the cookie outlived "
            "the grace window, or Redis dropped the key (restart/eviction/flush)."
        )

    return OnyxError(
        _REASON_TO_ERROR_CODE[rejection.reason],
        _REASON_TO_DETAIL[rejection.reason],
    )
