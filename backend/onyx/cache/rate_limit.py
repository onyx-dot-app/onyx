import hashlib
import time

from onyx.cache.factory import get_shared_cache_backend


def within_rate_limit(bucket: str, *, limit: int, window_seconds: int) -> bool:
    """Count one request against ``bucket`` and report whether it is within ``limit``
    for the current fixed window. Buckets are shared across tenants."""
    digest = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
    window = int(time.time() // window_seconds)
    count = get_shared_cache_backend().incr(
        f"rate_limit:{digest}:{window}", ex=window_seconds
    )
    return count <= limit
