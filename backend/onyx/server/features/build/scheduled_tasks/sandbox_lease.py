"""Redis-backed sandbox lease.

Each user owns exactly one sandbox (see `Sandbox.user_id` unique constraint).
This lease serializes prompt execution against that sandbox so an in-flight
scheduled run doesn't trample an interactive prompt (and vice versa).

Two callers acquire this lease:
- the interactive `send_message` path in `SessionManager`, around the
  streaming section;
- the scheduled-tasks executor, around the agent drive loop.

Implementation: a tenant-scoped Redis lock keyed on `sandbox_id`. The
`owner_token` argument lets a holder identify itself across acquire/release
boundaries — important because the executor and the interactive path live in
different processes (worker vs. api_server) and we want release to be a no-op
if the lock has already been released or expired (and re-acquired by someone
else).
"""

from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from redis.lock import Lock as RedisLock

from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Distinct key namespace so we don't collide with other `da_lock:*` users.
SANDBOX_LEASE_KEY_PREFIX = "da_lock:sandbox_lease"


def _lease_key(sandbox_id: UUID) -> str:
    return f"{SANDBOX_LEASE_KEY_PREFIX}:{sandbox_id}"


class SandboxLeaseAcquisitionError(Exception):
    """Raised when the sandbox lease cannot be acquired in the allotted time.

    The caller should surface this to the user (interactive path) or mark
    the scheduled run as `skipped`/`failed` (executor path).
    """


@contextmanager
def acquire_sandbox_lease(
    sandbox_id: UUID,
    owner_token: str,
    ttl_seconds: float,
    wait_seconds: float = 0.0,
) -> Generator[str, None, None]:
    """Acquire a sandbox lease for the duration of a `with` block.

    Args:
        sandbox_id: The sandbox to lock against.
        owner_token: Caller-provided identity. Stored as the lock's value;
            used by `release_sandbox_lease` (and the redis-py ``release``
            built-in) to ensure only the owning caller can release.
        ttl_seconds: Maximum time the lease can be held before Redis
            auto-releases it. Callers must keep their work under this.
        wait_seconds: How long to block waiting to acquire. ``0.0`` (the
            default) means non-blocking — fail immediately if held.

    Yields:
        The `owner_token` (for symmetry with ``redis_shared_lock``).

    Raises:
        SandboxLeaseAcquisitionError: lease was held by another caller and
            could not be acquired within ``wait_seconds``.
    """
    redis_client = get_redis_client()
    blocking = wait_seconds > 0.0
    lock: RedisLock = redis_client.lock(
        name=_lease_key(sandbox_id),
        timeout=ttl_seconds,
        blocking=blocking,
        blocking_timeout=wait_seconds if blocking else None,
    )

    if not lock.acquire(token=owner_token):
        raise SandboxLeaseAcquisitionError(
            f"Could not acquire sandbox lease for {sandbox_id} "
            f"within {wait_seconds:.3f}s (held by another caller)"
        )

    try:
        yield owner_token
    finally:
        try:
            if lock.owned():
                lock.release()
            else:
                # TTL expired or someone else stole the lease — log so
                # ops can see scheduled runs that ran past TTL.
                logger.warning(
                    "Sandbox lease %s no longer owned on release (token=%s).",
                    sandbox_id,
                    owner_token,
                )
        except Exception:
            logger.exception(
                "Error releasing sandbox lease %s (token=%s).",
                sandbox_id,
                owner_token,
            )


def release_sandbox_lease(sandbox_id: UUID, owner_token: str) -> bool:
    """Force-release a sandbox lease previously acquired with ``owner_token``.

    Idempotent: returns ``False`` (and does nothing) if the lease isn't
    currently held by this token (already released, TTL expired, or owned
    by someone else). The executor uses this to release on
    ``awaiting_approval`` (humans shouldn't block CPU); the lease is
    re-acquired on resume.

    Implementation: reconstructs a ``redis.lock.Lock`` bound to the same
    key+token and calls ``release()``, which runs the canonical
    compare-and-delete Lua script under the hood.

    Returns:
        ``True`` if a lease owned by ``owner_token`` was released; otherwise
        ``False``.
    """
    redis_client = get_redis_client()
    lock: RedisLock = redis_client.lock(
        name=_lease_key(sandbox_id),
        timeout=None,
        blocking=False,
    )
    # Bind the token so the lock thinks "we" own it; release() then runs the
    # standard CAS-delete script and raises LockNotOwnedError if the value
    # in Redis no longer matches our token. Stored as bytes because redis-py
    # writes the same form during acquire() — the Lua release script does a
    # byte-wise compare against the value in Redis.
    lock.local.token = owner_token.encode("utf-8")  # type: ignore[assignment]
    try:
        lock.release()
        return True
    except Exception as e:
        # redis.exceptions.LockNotOwnedError / LockError — common in this
        # path and not worth a stack trace.
        logger.debug(
            "Sandbox lease %s not released (token=%s): %s",
            sandbox_id,
            owner_token,
            e,
        )
        return False


def is_sandbox_leased(sandbox_id: UUID) -> bool:
    """Peek at whether the lease is currently held. Does not acquire."""
    return get_redis_client().exists(_lease_key(sandbox_id)) > 0
