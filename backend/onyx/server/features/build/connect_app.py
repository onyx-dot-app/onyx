"""Cache-backed connect-app requests, no DB or turn-side waiting.

The agent's no-op ``connect_app`` tool makes opencode pause the turn. The turn
consumer ``announces`` the request (so the live stream can emit a
``ConnectAppRequestPacket`` card) and ``stashes`` the context to answer it, then
keeps streaming. The decision endpoint loads that context and answers opencode
directly on the sandbox — allow (connected) / reject (declined) — and opencode
resumes. A session index lets new attachments restore pending cards. The pending
record expires with the permission wait, so old cards cannot be restored.
"""

import math
import time
from enum import Enum

from pydantic import BaseModel, ValidationError

from onyx.cache.interface import CacheBackend, CacheLockAcquisitionError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Each record only needs to outlive the user's connect/decline interaction.
_ANNOUNCE_TTL_S = 60
_PENDING_TTL_S = 60 * 30


class ConnectAppDecision(str, Enum):
    CONNECTED = "connected"
    DECLINED = "declined"


class ConnectAppRequest(BaseModel):
    """The connect prompt carried from the turn consumer to the live stream."""

    request_id: str
    external_app_id: int
    reason: str | None = None


class ConnectAppPending(BaseModel):
    """The context the decision endpoint needs to answer one connect_app
    permission on opencode, keyed by ``request_id``."""

    build_session_id: str
    opencode_session_id: str
    perm_id: str
    directory: str
    request: ConnectAppRequest | None = None
    expires_at: float | None = None


class _SessionRequests(BaseModel):
    request_ids: list[str]


def _session_key(session_id: str) -> str:
    return f"craft:connect_app:session:{session_id}"


def list_pending_requests(
    session_id: str, cache: CacheBackend
) -> list[ConnectAppRequest]:
    """Read still-actionable cards without consuming their announcements."""
    raw = cache.get(_session_key(session_id))
    if raw is None:
        return []
    try:
        index = _SessionRequests.model_validate_json(raw)
    except ValidationError:
        logger.warning("connect_app: unparseable session index for %s", session_id)
        return []
    requests: list[ConnectAppRequest] = []
    for request_id in index.request_ids:
        pending = load_pending(request_id, cache)
        if pending and pending.build_session_id == session_id and pending.request:
            requests.append(pending.request)
    return requests


def _announce_key(session_id: str) -> str:
    return f"craft:connect_app:announce:{session_id}"


def _pending_key(request_id: str) -> str:
    return f"craft:connect_app:pending:{request_id}"


def announce_request(
    session_id: str, request: ConnectAppRequest, cache: CacheBackend
) -> None:
    """Hand the request to the worker streaming SSE for ``session_id``."""
    key = _announce_key(session_id)
    cache.rpush(key, request.model_dump_json())
    cache.expire(key, _ANNOUNCE_TTL_S)


def pop_announcement(
    session_id: str, timeout_s: int, cache: CacheBackend
) -> ConnectAppRequest | None:
    """BLPOP one announced request; ``None`` on timeout/unparseable payload."""
    result = cache.blpop([_announce_key(session_id)], timeout_s)
    if result is None:
        return None
    _key, value = result
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return ConnectAppRequest.model_validate_json(value)
    except ValidationError:
        logger.warning("connect_app: unparseable announce %r for %s", value, session_id)
        return None


def stash_pending(
    request_id: str, pending: ConnectAppPending, cache: CacheBackend
) -> None:
    """Record how to answer this request's permission, for the decision endpoint."""
    ttl = (
        max(1, math.ceil(pending.expires_at - time.time()))
        if pending.expires_at is not None
        else _PENDING_TTL_S
    )
    cache.set(_pending_key(request_id), pending.model_dump_json(), ex=ttl)
    if pending.request is None:
        return
    key = _session_key(pending.build_session_id)
    lock = cache.lock(f"{key}:lock", timeout=10)
    if not lock.acquire(blocking=True, blocking_timeout=5):
        raise CacheLockAcquisitionError("Could not index the pending connect request")
    try:
        requests = list_pending_requests(pending.build_session_id, cache)
        request_ids = {request.request_id for request in requests}
        request_ids.add(request_id)
        index_ttl = max(
            [
                ttl,
                *(cache.ttl(_pending_key(request.request_id)) for request in requests),
            ]
        )
        cache.set(
            key,
            _SessionRequests(request_ids=sorted(request_ids)).model_dump_json(),
            ex=index_ttl,
        )
    finally:
        lock.release()


def load_pending(request_id: str, cache: CacheBackend) -> ConnectAppPending | None:
    """Load the answer context; ``None`` if expired/already cleared/unparseable."""
    raw = cache.get(_pending_key(request_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        pending = ConnectAppPending.model_validate_json(raw)
    except ValidationError:
        logger.warning("connect_app: unparseable pending for %s", request_id)
        return None
    if pending.expires_at is not None and pending.expires_at <= time.time():
        return None
    return pending


def clear_pending(request_id: str, cache: CacheBackend) -> None:
    cache.delete(_pending_key(request_id))
