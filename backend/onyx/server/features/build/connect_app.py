"""Connect-app request rendezvous.

When the agent calls the no-op ``connect_app`` tool, opencode emits a permission
request. The turn-driving consumer (``serve_client``) announces it here; the
separate live-stream consumer (``merge_events_with_announces``) picks the
announce up and emits a ``ConnectAppRequestPacket`` rendered as a card on the
frontend. The user's connect/reject decision is delivered back and unblocks the
parked turn.

Two Redis channels, both keyed so the blocked turn and the decision request can
land on different api-server workers:

* ``announce`` — carries the request to whichever worker holds the user's live
  SSE stream (the turn-driving worker does not relay to the browser itself).
* ``decision`` — a single-shot latch carrying the user's answer back to the
  parked turn.

This deliberately avoids the ActionApproval machinery (no DB row, no ``/live``
poll): the permission already blocks the agent, so all we move is one request up
and one decision back.
"""

import time
from enum import Enum

from pydantic import BaseModel
from pydantic import ValidationError

from onyx.cache.interface import CacheBackend
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The decision outlives a brief worker hiccup but not a stale request.
_DECISION_TTL_S = 60 * 30
# Only needs to outlive the gap between the announce and the live stream's BLPOP.
_ANNOUNCE_TTL_S = 60


class ConnectAppDecision(str, Enum):
    CONNECTED = "connected"
    DECLINED = "declined"


class ConnectAppRequest(BaseModel):
    """The connect prompt carried from the turn consumer to the live stream."""

    request_id: str
    app_slug: str
    reason: str | None = None


def _decision_key(request_id: str) -> str:
    return f"craft:connect_app:decision:{request_id}"


def _announce_key(session_id: str) -> str:
    return f"craft:connect_app:announce:{session_id}"


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


def resolve(request_id: str, decision: ConnectAppDecision, cache: CacheBackend) -> None:
    """Deliver the user's decision to the parked turn waiting on ``request_id``."""
    key = _decision_key(request_id)
    cache.rpush(key, decision.value)
    cache.expire(key, _DECISION_TTL_S)


def wait_for_decision(
    request_id: str, timeout_s: int, cache: CacheBackend
) -> ConnectAppDecision | None:
    """Block until the user resolves ``request_id``; ``None`` on timeout.

    Polls in short BLPOP slices so an overall long wait stays responsive to
    process shutdown. Called from the (synchronous) opencode event consumer.
    """
    if timeout_s <= 0:
        return None

    key = _decision_key(request_id)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = cache.blpop([key], 1)
        if result is None:
            continue
        _key, value = result
        if isinstance(value, bytes):
            value = value.decode()
        try:
            return ConnectAppDecision(value)
        except ValueError:
            logger.warning(
                "connect_app: unparseable decision %r for %s", value, request_id
            )
            return None
    return None
