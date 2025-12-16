"""
Redis-based caching helper for database query results.

This module provides caching functionality that works across all pods
in the deployment, unlike @lru_cache which is process-local.
"""

import pickle
from collections.abc import Callable
from functools import wraps
from typing import Any
from typing import TypeVar

from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

T = TypeVar("T")


def redis_cache_query(
    cache_key_prefix: str,
    ttl_seconds: int = 60,
) -> Callable:
    """
    Decorator to cache database query results in Redis.

    Args:
        cache_key_prefix: Prefix for the Redis key (e.g., "document_sets")
        ttl_seconds: Time to live in seconds (default 60s)

    Usage:
        @redis_cache_query("document_sets", ttl_seconds=60)
        def fetch_document_sets(user_id, db_session, include_outdated=False):
            # Your expensive query here
            return results

    The cache key will be constructed as:
        {tenant_id}:cache:{prefix}:{arg1}:{arg2}:...

    Benefits over @lru_cache:
        - Shared across ALL pods (167 in your case)
        - Automatic TTL-based expiration
        - Can be invalidated from any pod
        - Doesn't cause memory bloat in individual processes
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Build cache key from function arguments
            # Skip db_session as it's not hashable
            cache_key_parts = [cache_key_prefix]

            # Add args (skip first if it's db_session/self)
            for arg in args:
                arg_name = type(arg).__name__
                if "Session" not in arg_name and "self" not in str(arg):
                    cache_key_parts.append(str(arg))

            # Add kwargs
            for k, v in sorted(kwargs.items()):
                if "session" not in k.lower():
                    cache_key_parts.append(f"{k}={v}")

            cache_key = f"cache:{':'.join(cache_key_parts)}"

            # Try to get from cache
            r = get_redis_client()

            try:
                cached_data = r.get(cache_key)
                if cached_data:
                    logger.debug(f"Cache HIT for {cache_key}")
                    return pickle.loads(cached_data)
            except Exception as e:
                logger.warning(f"Cache read error for {cache_key}: {e}")
                # Continue to query DB on cache errors

            # Cache miss - execute the actual function
            logger.debug(f"Cache MISS for {cache_key}")
            result = func(*args, **kwargs)

            # Store in cache
            try:
                r.setex(cache_key, ttl_seconds, pickle.dumps(result))
            except Exception as e:
                logger.warning(f"Cache write error for {cache_key}: {e}")
                # Don't fail the request if cache write fails

            return result

        # Add cache invalidation method
        def invalidate_cache(cache_key_suffix: str = "*") -> int:
            """
            Invalidate cache entries.

            Args:
                cache_key_suffix: Pattern to match keys (default: all keys for this prefix)

            Returns:
                Number of keys deleted
            """
            r = get_redis_client()
            pattern = f"cache:{cache_key_prefix}:{cache_key_suffix}"

            deleted_count = 0
            for key in r.scan_iter(match=pattern, count=1000):
                r.delete(key)
                deleted_count += 1

            logger.info(
                f"Invalidated {deleted_count} cache entries for pattern: {pattern}"
            )
            return deleted_count

        wrapper.invalidate_cache = invalidate_cache  # type: ignore

        return wrapper

    return decorator


def invalidate_all_query_caches() -> int:
    """
    Invalidate ALL query caches across the system.
    Useful for manual cache clearing or after major data changes.

    Returns:
        Total number of cache keys deleted
    """
    r = get_redis_client()
    pattern = "cache:*"

    deleted_count = 0
    for key in r.scan_iter(match=pattern, count=1000):
        r.delete(key)
        deleted_count += 1

    logger.info(f"Invalidated {deleted_count} total query cache entries")
    return deleted_count
