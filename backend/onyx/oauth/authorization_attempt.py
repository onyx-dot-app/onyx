import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Generic, cast

from pydantic import ValidationError

from onyx.cache.interface import CacheBackend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.models import AuthorizationAttempt, PayloadT
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_KEY_PREFIX = "oauth:authorization_attempt:v1"
_INVALID_ATTEMPT_MESSAGE = "Invalid or expired OAuth authorization attempt"
MAX_AUTHORIZATION_ATTEMPT_TTL_SECONDS = 10 * 60


class AuthorizationAttemptStore(Generic[PayloadT]):
    """Stores typed OAuth attempts in a tenant-scoped cache."""

    def __init__(
        self,
        cache: CacheBackend,
        *,
        namespace: str,
        payload_type: type[PayloadT],
        ttl_seconds: int,
    ) -> None:
        if not _NAMESPACE_PATTERN.fullmatch(namespace) or len(namespace) > 64:
            raise ValueError("OAuth attempt namespace is invalid")
        if not 0 < ttl_seconds <= MAX_AUTHORIZATION_ATTEMPT_TTL_SECONDS:
            raise ValueError(
                "OAuth attempt TTL must be between 1 and "
                f"{MAX_AUTHORIZATION_ATTEMPT_TTL_SECONDS} seconds"
            )

        self._cache = cache
        self._namespace = namespace
        self._attempt_type = cast(
            type[AuthorizationAttempt[PayloadT]],
            AuthorizationAttempt.__class_getitem__(payload_type),
        )
        self._ttl_seconds = ttl_seconds

    def store(
        self,
        *,
        owner_id: str,
        payload: PayloadT,
        state: str | None = None,
    ) -> AuthorizationAttempt[PayloadT]:
        """Persist a new attempt.

        When supplied, ``state`` must come from a cryptographically secure
        generator. Its entropy cannot be established through format validation.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        attempt = self._attempt_type(
            namespace=self._namespace,
            owner_id=owner_id,
            state=state if state is not None else generate_authorization_state(),
            expires_at=expires_at,
            payload=payload,
        )
        stored = self._cache.set_if_absent(
            self._key(attempt.owner_id, attempt.state),
            attempt.model_dump_json(),
            ex=self._ttl_seconds,
        )
        if not stored:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "An OAuth authorization attempt already uses this state",
            )
        return attempt

    def consume(
        self,
        *,
        owner_id: str,
        state: str,
    ) -> AuthorizationAttempt[PayloadT]:
        stored = self._cache.getdel(self._key(owner_id, state))
        if stored is None:
            raise _invalid_attempt_error()

        try:
            attempt = self._attempt_type.model_validate_json(stored)
        except (ValidationError, ValueError, TypeError) as error:
            logger.warning(
                "Rejected malformed OAuth authorization attempt (%s)",
                type(error).__name__,
            )
            raise _invalid_attempt_error() from error

        if (
            attempt.namespace != self._namespace
            or attempt.owner_id != owner_id
            or not secrets.compare_digest(attempt.state, state)
            or attempt.expires_at <= datetime.now(timezone.utc)
        ):
            raise _invalid_attempt_error()
        return attempt

    def _key(self, owner_id: str, state: str) -> str:
        owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        return f"{_KEY_PREFIX}:{self._namespace}:{owner_hash}:{state_hash}"


def generate_authorization_state() -> str:
    """Generate a 256-bit, URL-safe OAuth state value."""
    return secrets.token_urlsafe(32)


def _invalid_attempt_error() -> OnyxError:
    return OnyxError(OnyxErrorCode.INVALID_INPUT, _INVALID_ATTEMPT_MESSAGE)
