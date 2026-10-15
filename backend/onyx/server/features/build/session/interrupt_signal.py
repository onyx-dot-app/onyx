"""Cross-replica cancellation fences owned by interactive Craft turns."""

from uuid import UUID

from onyx.cache.interface import CacheBackend

FENCE_PREFIX = "buildturninterrupt_fence"
# Abandoned turn fences expire even if their runner cannot clear them.
FENCE_TTL = 10 * 60


def _fence_key(turn_id: UUID) -> str:
    # Tenant isolation is handled by the cache backend's key-prefixing.
    return f"{FENCE_PREFIX}_{turn_id}"


def request_interrupt(turn_id: UUID, cache: CacheBackend) -> None:
    """Request cancellation of this turn."""
    cache.set(_fence_key(turn_id), 0, ex=FENCE_TTL)


def is_interrupt_requested(turn_id: UUID, cache: CacheBackend) -> bool:
    return cache.exists(_fence_key(turn_id))


def clear_interrupt(turn_id: UUID, cache: CacheBackend) -> None:
    """Clear the completed turn's cancellation fence."""
    cache.delete(_fence_key(turn_id))
