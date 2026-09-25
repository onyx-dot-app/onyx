"""Cross-replica interrupt fence for build (Craft) sessions.

A direct opencode-serve abort only works once the session's opencode id has
been minted, which on the first turn happens lazily *inside* the streaming
request. An interrupt arriving during that window can't abort anything. This
fence closes that race: the interrupt endpoint sets a flag the streaming flow
checks at the point the opencode session becomes known and on every event
thereafter, aborting itself when set. Backed by the tenant-aware cache so it
works across api_server replicas (mirrors ``onyx.chat.stop_signal_checker``).
"""

from uuid import UUID

from onyx.cache.interface import CacheBackend

FENCE_PREFIX = "buildsessioninterrupt_fence"
# Backstop: a turn never outlives this, so a fence can't leak past one.
FENCE_TTL = 10 * 60


def _fence_key(session_id: UUID) -> str:
    # Tenant isolation is handled by the cache backend's key-prefixing.
    return f"{FENCE_PREFIX}_{session_id}"


def request_interrupt(session_id: UUID, cache: CacheBackend) -> None:
    """Signal that the in-flight turn for this session should be interrupted."""
    cache.set(_fence_key(session_id), 0, ex=FENCE_TTL)


def is_interrupt_requested(session_id: UUID, cache: CacheBackend) -> bool:
    return cache.exists(_fence_key(session_id))


def clear_interrupt(session_id: UUID, cache: CacheBackend) -> None:
    """Clear the fence — called at the start and end of each turn."""
    cache.delete(_fence_key(session_id))
