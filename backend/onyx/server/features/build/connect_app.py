"""Connect-app request plumbing — two Redis records, no DB, no turn-side waiting.

The agent's no-op ``connect_app`` tool makes opencode pause the turn. The turn
consumer ``announces`` the request (so the live stream can emit a
``ConnectAppRequestPacket`` card) and ``stashes`` the context to answer it, then
keeps streaming. The decision endpoint loads that context and answers opencode
directly on the sandbox — allow (connected) / reject (declined) — and opencode
resumes. Both records are keyed so the producing, live-stream, and decision
workers can be different processes.
"""

from enum import Enum

from pydantic import BaseModel
from pydantic import ValidationError

from onyx.cache.interface import CacheBackend
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
    app_slug: str
    reason: str | None = None


class ConnectAppPending(BaseModel):
    """The context the decision endpoint needs to answer one connect_app
    permission on opencode, keyed by ``request_id``."""

    build_session_id: str
    opencode_session_id: str
    perm_id: str
    directory: str


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
    cache.set(_pending_key(request_id), pending.model_dump_json(), ex=_PENDING_TTL_S)


def load_pending(request_id: str, cache: CacheBackend) -> ConnectAppPending | None:
    """Load the answer context; ``None`` if expired/already cleared/unparseable."""
    raw = cache.get(_pending_key(request_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return ConnectAppPending.model_validate_json(raw)
    except ValidationError:
        logger.warning("connect_app: unparseable pending for %s", request_id)
        return None


def clear_pending(request_id: str, cache: CacheBackend) -> None:
    cache.delete(_pending_key(request_id))
