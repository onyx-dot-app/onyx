import time
from uuid import UUID, uuid4

from onyx.cache.interface import CacheBackend, CacheLock, CacheLockLostError
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

PREFIX = "chatprocessing"
FENCE_PREFIX = f"{PREFIX}_fence"
PREPARATION_LEASE_SECONDS = 30 * 60
ACTIVE_LEASE_SECONDS = 60
ADMISSION_CACHE_TIMEOUT_S = 1.0
PROCESSING_REFRESH_INTERVAL_S = 5.0
_ADMISSION_LOCK_TTL_SECONDS = 30
_ADMISSION_LOCK_WAIT_SECONDS = 5
_ADMISSION_EXPIRY_MARGIN_SECONDS = 5


def _get_fence_key(chat_session_id: UUID) -> str:
    """Generate the cache key for a chat session processing fence.

    Args:
        chat_session_id: The UUID of the chat session

    Returns:
        The fence key string. Tenant isolation is handled automatically
        by the cache backend (Redis key-prefixing or Postgres schema routing).
    """
    return f"{FENCE_PREFIX}_{chat_session_id}"


class ChatTurnAdmission:
    """Keep one turn admitted until its execution and storage have drained.

    Preparation has no heartbeat, so its lease permits slow file loading.
    Publishing starts a short lease renewed by the existing control thread.
    """

    def __init__(self, cache: CacheBackend) -> None:
        self.cache = cache
        self._session_id: UUID | None = None
        self._token = uuid4().hex.encode()
        self._last_refresh = time.monotonic()
        self._lease_seconds = PREPARATION_LEASE_SECONDS

    def _lock(self, session_id: UUID) -> CacheLock:
        lock = self.cache.lock(
            f"{PREFIX}_admission_lock_{session_id}", timeout=_ADMISSION_LOCK_TTL_SECONDS
        )
        if not lock.acquire(blocking_timeout=_ADMISSION_LOCK_WAIT_SECONDS):
            raise RuntimeError("Could not lock chat session admission")
        return lock

    @staticmethod
    def _owner_key(session_id: UUID) -> str:
        return f"{PREFIX}_owner_{session_id}"

    def claim(self, session_id: UUID) -> None:
        lock = self._lock(session_id)
        try:
            started = time.monotonic()
            self._session_id = session_id
            if not self.cache.set_if_absent(
                self._owner_key(session_id), self._token, ex=self._lease_seconds
            ):
                raise OnyxError(
                    OnyxErrorCode.CONFLICT,
                    "This chat session is still processing its previous message.",
                )
            self._last_refresh = started
            self.cache.set(_get_fence_key(session_id), 0, ex=self._lease_seconds)
        finally:
            lock.release()

    def _check_deadline(self) -> None:
        if (
            time.monotonic() - self._last_refresh
            >= self._lease_seconds - _ADMISSION_EXPIRY_MARGIN_SECONDS
        ):
            raise CacheLockLostError("Chat session admission renewal expired")

    def _renew_owner(self, session_id: UUID, lease_seconds: int) -> None:
        self._check_deadline()
        started = time.monotonic()
        # A lost reply may still shorten the lease. Keep its conservative deadline.
        self._lease_seconds = lease_seconds
        if not self.cache.renew_if_value(
            self._owner_key(session_id), self._token, lease_seconds
        ):
            raise CacheLockLostError("Chat session admission was lost")
        if (
            time.monotonic() - started
            >= lease_seconds - _ADMISSION_EXPIRY_MARGIN_SECONDS
        ):
            raise CacheLockLostError("Chat session admission renewal expired")
        self._last_refresh = started

    def publish(self, stream_id: int) -> None:
        session_id = self._session_id
        if session_id is None:
            raise RuntimeError("Chat turn has no admission")
        self._check_deadline()
        lock = self._lock(session_id)
        try:
            self._renew_owner(session_id, ACTIVE_LEASE_SECONDS)
            self.cache.set(
                _get_fence_key(session_id), stream_id, ex=self._lease_seconds
            )
        finally:
            lock.release()

    def refresh(self) -> None:
        session_id = self._session_id
        if session_id is None:
            raise RuntimeError("Chat turn has no admission")
        self._check_deadline()
        lock = self._lock(session_id)
        try:
            self._renew_owner(session_id, self._lease_seconds)
            self.cache.expire(_get_fence_key(session_id), self._lease_seconds)
        finally:
            lock.release()

    def release(self) -> None:
        session_id = self._session_id
        if session_id is None:
            return
        lock = self._lock(session_id)
        try:
            if self.cache.get(self._owner_key(session_id)) == self._token:
                self.cache.delete(_get_fence_key(session_id))
                self.cache.delete(self._owner_key(session_id))
            self._session_id = None
        finally:
            lock.release()


def get_processing_stream_id(chat_session_id: UUID, cache: CacheBackend) -> int | None:
    """Stream ID of the session's in-flight stream buffer, or None when idle or the
    fence carries no stream ID."""
    if not is_chat_session_processing(chat_session_id, cache):
        return None
    raw = cache.get(_get_fence_key(chat_session_id))
    if raw is None:
        return None
    try:
        stream_id = int(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.warning(
            "invalid processing stream ID for session %s: %r",
            chat_session_id,
            raw,
        )
        return None
    return stream_id if stream_id > 0 else None


def is_chat_session_processing(chat_session_id: UUID, cache: CacheBackend) -> bool:
    """Check if the chat session is processing a message.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend

    Returns:
        True if the chat session is processing a message, False otherwise
    """
    # Stream metadata can outlive a lease when a process exits during publication.
    return cache.exists(ChatTurnAdmission._owner_key(chat_session_id))
