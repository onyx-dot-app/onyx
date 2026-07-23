"""Cross-process invalidation for the tenant -> shard routing cache.

Every process caches tenant -> shard resolutions in memory (see ``shard_routing``).
When the migrator moves a tenant it flips the ``tenant_shard`` row, but each process
keeps serving its cached answer until that entry expires. Routing a request with a
stale answer sends reads *and writes* to the database the tenant just moved off, so
the TTL alone is not an acceptable propagation mechanism during a migration.

This module adds a shared version counter in Redis. The migrator bumps it after a
flip; every process re-reads it on a short interval and drops its whole local cache
when it changes. Propagation is bounded by the poll interval rather than the TTL.

Two deliberate choices:

- **Read from the primary, not a replica.** This is one GET per process per poll
  interval, so the cost is negligible, and it keeps replica lag out of the
  correctness argument for a flip.
- **Redis failure does not invalidate.** If the version cannot be read the local
  cache is left alone and the TTL remains the backstop, i.e. behavior degrades to
  what it would have been without this module. The consequence is that the
  migrator must treat Redis as a *precondition* for a flip, not an optimization —
  see ``shard_map_propagation_seconds``.
"""

import threading
import time

from onyx.configs.app_configs import (
    ONYX_DB_SHARD_MAP_TTL_SECONDS,
    ONYX_DB_SHARD_MAP_VERSION_POLL_SECONDS,
)
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Global (not per-tenant) key, namespaced under the cloud tenant by convention —
# the same one `GATED_TENANTS_KEY` uses.
SHARD_MAP_VERSION_KEY = "db_shard_map_version"

# Safety margin added to the poll interval so a migrator's wait covers a process
# that had just finished a poll when the bump landed.
_PROPAGATION_MARGIN_SECONDS = 2.0


class _VersionPoller:
    """Throttled reader of the shared version counter."""

    _lock = threading.Lock()
    _last_polled_at: float | None = None
    _last_seen_version: str | None = None
    # None = never polled. Distinct from False so the *first* failure still logs;
    # starting at False would silently swallow an outage present from boot.
    _redis_healthy: bool | None = None

    @classmethod
    def _read_version(cls) -> str | None:
        # Imported lazily: this module sits under the request hot path and the
        # redis package pulls in a large import graph.
        from onyx.redis.redis_pool import get_redis_client

        client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
        raw = client.get(SHARD_MAP_VERSION_KEY)
        if raw is None:
            # Never bumped. A stable sentinel keeps this from looking like a change
            # on every poll.
            return "0"
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    @classmethod
    def poll(cls) -> bool:
        """Re-read the version if the interval has elapsed.

        Returns True when the version changed, meaning callers should drop cached
        routing. Never raises: a Redis problem is reported and treated as "no
        change", leaving the TTL as the backstop.
        """
        now = time.monotonic()
        last = cls._last_polled_at
        if last is not None and now - last < ONYX_DB_SHARD_MAP_VERSION_POLL_SECONDS:
            return False

        # Non-blocking: if another thread is already polling, use its result next
        # time rather than piling up on Redis.
        if not cls._lock.acquire(blocking=False):
            return False
        try:
            # Re-check under the lock; the winner may have just refreshed.
            last = cls._last_polled_at
            if (
                last is not None
                and time.monotonic() - last < ONYX_DB_SHARD_MAP_VERSION_POLL_SECONDS
            ):
                return False

            try:
                version = cls._read_version()
            except Exception:
                was_healthy = cls._redis_healthy
                cls._redis_healthy = False
                # Only log the transition, so a Redis outage does not emit a line
                # per poll per process. `None` (never polled) counts as a transition.
                if was_healthy is not False:
                    logger.warning(
                        "Could not read the shard map version from Redis; tenant "
                        "routing falls back to its %ss TTL until Redis recovers",
                        ONYX_DB_SHARD_MAP_TTL_SECONDS,
                        exc_info=True,
                    )
                # Deliberately updated on failure too, so a hard-down Redis is
                # retried on the interval rather than on every single request.
                cls._last_polled_at = time.monotonic()
                return False

            cls._last_polled_at = time.monotonic()
            cls._redis_healthy = True

            previous = cls._last_seen_version
            cls._last_seen_version = version
            if previous is None or previous == version:
                return False

            logger.info(
                "Shard map version changed (%s -> %s); dropping cached tenant routing",
                previous,
                version,
            )
            return True
        finally:
            cls._lock.release()

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._last_polled_at = None
            cls._last_seen_version = None
            cls._redis_healthy = None


def poll_shard_map_version() -> bool:
    """True if the shared shard map changed since this process last looked."""
    return _VersionPoller.poll()


def reset_shard_map_version_poller() -> None:
    """Forget the observed version. For tests and forked children."""
    _VersionPoller.reset()


def bump_shard_map_version() -> int:
    """Signal that the tenant -> shard map changed.

    Must be called by the migrator *after* committing a ``tenant_shard`` flip and
    *before* unfreezing the tenant. Raises if Redis is unreachable — a flip whose
    invalidation cannot be published is not safe to proceed from.
    """
    from onyx.redis.redis_pool import get_redis_client

    client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    version = int(client.incr(SHARD_MAP_VERSION_KEY))
    logger.info("Bumped shard map version to %s", version)
    return version


def shard_map_propagation_seconds() -> float:
    """How long to wait after a bump before every process is guaranteed current.

    This is the minimum a tenant must stay frozen after its map entry is flipped.

    It is bounded by the **TTL**, not the poll interval. A successful
    ``bump_shard_map_version`` only proves the *migrator* reached Redis; a serving
    process that is partitioned from Redis never observes the bump and keeps its
    cached mapping until it expires on its own. The TTL is therefore the real
    worst-case, and the freeze has to outlast it or an unfrozen tenant can still be
    routed to its old database by exactly the pod that could not be told.

    The Redis channel makes the common case fast; it does not improve this bound.
    """
    return (
        max(
            ONYX_DB_SHARD_MAP_VERSION_POLL_SECONDS,
            float(ONYX_DB_SHARD_MAP_TTL_SECONDS),
        )
        + _PROPAGATION_MARGIN_SECONDS
    )
