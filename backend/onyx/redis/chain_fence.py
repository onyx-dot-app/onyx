"""Token-fenced Redis markers for self-chaining Celery cleanup sweeps.

A "chain" is a sequence of tasks that each process one batch and enqueue the
next. A dispatcher claims the marker with a fresh token before sending the
first task (SET NX EX); each chained task then extends the lease only while it
still owns the marker. If a slow batch outlives the lease and a later beat
starts a replacement chain, the superseded task can neither extend nor delete
the new chain's marker — it just exits. This guarantees at most one chain per
tenant per marker key.
"""

from onyx.redis.tenant_redis_client import TenantRedisClient

# Extend the chain lease only if we still own it (marker value == our token).
# Returns 1 when owned+extended, 0 otherwise. Prevents a task whose lease lapsed
# (and whose chain a later beat has replaced) from extending someone else's lease.
_REFRESH_IF_OWNED = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
"""

# Release the chain marker only if we still own it.
_RELEASE_IF_OWNED = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def claim_chain(
    redis_client: TenantRedisClient, key: str, token: str, expires: int
) -> bool:
    """Claim the chain marker with ``token``. False means a chain is in flight
    (its active task may not be sitting in the queue), so don't start another."""
    return bool(redis_client.set(key, token, nx=True, ex=expires))


def refresh_chain_if_owned(
    redis_client: TenantRedisClient, key: str, token: str, expires: int
) -> bool:
    """Extend the chain lease iff ``token`` still owns the marker."""
    return bool(redis_client.eval(_REFRESH_IF_OWNED, [key], [token, str(expires)]))


def release_chain_if_owned(
    redis_client: TenantRedisClient, key: str, token: str
) -> None:
    """Delete the chain marker only if ``token`` still owns it."""
    redis_client.eval(_RELEASE_IF_OWNED, [key], [token])
