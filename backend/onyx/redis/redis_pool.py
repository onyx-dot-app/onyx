import asyncio
import functools
import json
import ssl
import threading
from collections.abc import Callable
from typing import Any
from typing import cast
from typing import Optional

import redis
from fastapi import Request
from redis import asyncio as aioredis
from redis.client import Redis
from redis.lock import Lock as RedisLock

from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.app_configs import REDIS_DB_NUMBER
from onyx.configs.app_configs import REDIS_HEALTH_CHECK_INTERVAL
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PASSWORD
from onyx.configs.app_configs import REDIS_POOL_MAX_CONNECTIONS
from onyx.configs.app_configs import REDIS_PORT
from onyx.configs.app_configs import REDIS_REPLICA_HOST
from onyx.configs.app_configs import REDIS_SSL
from onyx.configs.app_configs import REDIS_SSL_CA_CERTS
from onyx.configs.app_configs import REDIS_SSL_CERT_REQS
from onyx.configs.app_configs import USE_REDIS_IAM_AUTH
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.configs.constants import REDIS_SOCKET_KEEPALIVE_OPTIONS
from onyx.redis.iam_auth import configure_redis_iam_auth
from onyx.redis.iam_auth import create_redis_ssl_context_if_iam
from onyx.utils.logger import setup_logger
from shared_configs.configs import DEFAULT_REDIS_PREFIX
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

SCAN_ITER_COUNT_DEFAULT = 4096


class TenantRedis(redis.Redis):
    def __init__(self, tenant_id: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tenant_id: str = tenant_id

    def _prefixed(self, key: str | bytes | memoryview) -> str | bytes | memoryview:
        prefix: str = f"{self.tenant_id}:"
        if isinstance(key, str):
            if key.startswith(prefix):
                return key
            else:
                return prefix + key
        elif isinstance(key, bytes):
            prefix_bytes = prefix.encode()
            if key.startswith(prefix_bytes):
                return key
            else:
                return prefix_bytes + key
        elif isinstance(key, memoryview):
            key_bytes = key.tobytes()
            prefix_bytes = prefix.encode()
            if key_bytes.startswith(prefix_bytes):
                return key
            else:
                return memoryview(prefix_bytes + key_bytes)
        else:
            raise TypeError(f"Unsupported key type: {type(key)}")

    def _prefix_method(self, method: Callable) -> Callable:
        @functools.wraps(method)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if "name" in kwargs:
                kwargs["name"] = self._prefixed(kwargs["name"])
            elif len(args) > 0:
                args = (self._prefixed(args[0]),) + args[1:]
            return method(*args, **kwargs)

        return wrapper

    def _prefix_scan_iter(self, method: Callable) -> Callable:
        @functools.wraps(method)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Prefix the match pattern if provided
            if "match" in kwargs:
                kwargs["match"] = self._prefixed(kwargs["match"])
            elif len(args) > 0:
                args = (self._prefixed(args[0]),) + args[1:]

            # Get the iterator
            iterator = method(*args, **kwargs)

            # Remove prefix from returned keys
            prefix = f"{self.tenant_id}:".encode()
            prefix_len = len(prefix)

            for key in iterator:
                if isinstance(key, bytes) and key.startswith(prefix):
                    yield key[prefix_len:]
                else:
                    yield key

        return wrapper

    def __getattribute__(self, item: str) -> Any:
        original_attr = super().__getattribute__(item)
        methods_to_wrap = [
            "lock",
            "unlock",
            "get",
            "set",
            "delete",
            "exists",
            "incrby",
            "hset",
            "hget",
            "getset",
            "owned",
            "reacquire",
            "create_lock",
            "startswith",
            "smembers",
            "sismember",
            "sadd",
            "srem",
            "scard",
            "hexists",
            "hset",
            "hdel",
            "ttl",
            "pttl",
        ]  # Regular methods that need simple prefixing

        if item == "scan_iter" or item == "sscan_iter":
            return self._prefix_scan_iter(original_attr)
        elif item in methods_to_wrap and callable(original_attr):
            return self._prefix_method(original_attr)
        return original_attr


class RedisPool:
    _instance: Optional["RedisPool"] = None
    _lock: threading.Lock = threading.Lock()
    _pool: redis.BlockingConnectionPool
    _replica_pool: redis.BlockingConnectionPool

    def __new__(cls) -> "RedisPool":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(RedisPool, cls).__new__(cls)
                    cls._instance._init_pools()
        return cls._instance

    def _init_pools(self) -> None:
        self._pool = RedisPool.create_pool(ssl=REDIS_SSL)
        self._replica_pool = RedisPool.create_pool(
            host=REDIS_REPLICA_HOST, ssl=REDIS_SSL
        )

    def get_client(self, tenant_id: str) -> Redis:
        return TenantRedis(tenant_id, connection_pool=self._pool)

    def get_replica_client(self, tenant_id: str) -> Redis:
        return TenantRedis(tenant_id, connection_pool=self._replica_pool)

    def get_raw_client(self) -> Redis:
        """
        Returns a Redis client with direct access to the primary connection pool,
        without tenant prefixing.
        """
        return redis.Redis(connection_pool=self._pool)

    def get_raw_replica_client(self) -> Redis:
        """
        Returns a Redis client with direct access to the replica connection pool,
        without tenant prefixing.
        """
        return redis.Redis(connection_pool=self._replica_pool)

    @staticmethod
    def create_pool(
        host: str = REDIS_HOST,
        port: int = REDIS_PORT,
        db: int = REDIS_DB_NUMBER,
        password: str = REDIS_PASSWORD,
        max_connections: int = REDIS_POOL_MAX_CONNECTIONS,
        ssl_ca_certs: str | None = REDIS_SSL_CA_CERTS,
        ssl_cert_reqs: str = REDIS_SSL_CERT_REQS,
        ssl: bool = False,
    ) -> redis.BlockingConnectionPool:
        """
        Create a Redis connection pool with appropriate SSL configuration.
        SSL Configuration Priority:
        1. IAM Authentication (USE_REDIS_IAM_AUTH=true): Uses system CA certificates
        2. Regular SSL (REDIS_SSL=true): Uses custom SSL configuration
        3. No SSL: Standard connection without encryption
        Note: IAM authentication automatically enables SSL and takes precedence
        over regular SSL configuration to ensure proper security.

        We use BlockingConnectionPool because it will block and wait for a connection
        rather than error if max_connections is reached. This is far more deterministic
        behavior and aligned with how we want to use Redis."""

        # Using ConnectionPool is not well documented.
        # Useful examples: https://github.com/redis/redis-py/issues/780

        # Handle IAM authentication
        if USE_REDIS_IAM_AUTH:
            # For IAM authentication, we don't use password
            # and ensure SSL is enabled with proper context
            ssl_context = create_redis_ssl_context_if_iam()
            return redis.BlockingConnectionPool(
                host=host,
                port=port,
                db=db,
                password=None,  # No password with IAM auth
                max_connections=max_connections,
                timeout=None,
                health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
                socket_keepalive=True,
                socket_keepalive_options=REDIS_SOCKET_KEEPALIVE_OPTIONS,
                connection_class=redis.SSLConnection,
                ssl_context=ssl_context,  # Use IAM auth SSL context
            )

        if ssl:
            return redis.BlockingConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                timeout=None,
                health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
                socket_keepalive=True,
                socket_keepalive_options=REDIS_SOCKET_KEEPALIVE_OPTIONS,
                connection_class=redis.SSLConnection,
                ssl_ca_certs=ssl_ca_certs,
                ssl_cert_reqs=ssl_cert_reqs,
            )

        return redis.BlockingConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=max_connections,
            timeout=None,
            health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
            socket_keepalive=True,
            socket_keepalive_options=REDIS_SOCKET_KEEPALIVE_OPTIONS,
        )


redis_pool = RedisPool()


# # Usage example
# redis_pool = RedisPool()
# redis_client = redis_pool.get_client()

# # Example of setting and getting a value
# redis_client.set('key', 'value')
# value = redis_client.get('key')
# print(value.decode())  # Output: 'value'


def get_redis_client(
    *,
    #  This argument will be deprecated in the future
    tenant_id: str | None = None,
) -> Redis:
    """
    Returns a Redis client with tenant-specific key prefixing.

    This ensures proper data isolation between tenants by automatically
    prefixing all Redis keys with the tenant ID.

    Use this when working with tenant-specific data that should be
    isolated from other tenants.
    """
    if tenant_id is None:
        tenant_id = get_current_tenant_id()

    return redis_pool.get_client(tenant_id)


def get_redis_replica_client(
    *,
    # this argument will be deprecated in the future
    tenant_id: str | None = None,
) -> Redis:
    """
    Returns a Redis replica client with tenant-specific key prefixing.

    Similar to get_redis_client(), but connects to a read replica when available.
    This ensures proper data isolation between tenants by automatically
    prefixing all Redis keys with the tenant ID.

    Use this for read-heavy operations on tenant-specific data.
    """
    if tenant_id is None:
        tenant_id = get_current_tenant_id()

    return redis_pool.get_replica_client(tenant_id)


def get_shared_redis_client() -> Redis:
    """
    Returns a Redis client with a shared namespace prefix.

    Unlike tenant-specific clients, this uses a common prefix for all keys,
    creating a shared namespace accessible across all tenants.

    Use this for data that should be shared across the application and
    isn't specific to any individual tenant.
    """
    return redis_pool.get_client(DEFAULT_REDIS_PREFIX)


def get_shared_redis_replica_client() -> Redis:
    """
    Returns a Redis replica client with a shared namespace prefix.

    Similar to get_shared_redis_client(), but connects to a read replica when available.
    Uses a common prefix for all keys, creating a shared namespace.

    Use this for read-heavy operations on data that should be shared
    across the application.
    """
    return redis_pool.get_replica_client(DEFAULT_REDIS_PREFIX)


def get_raw_redis_client() -> Redis:
    """
    Returns a Redis client that doesn't apply tenant prefixing to keys.

    Use this only when you need to access Redis directly without tenant isolation
    or any key prefixing. Typically needed for integrating with external systems
    or libraries that have inflexible key requirements.

    Warning: Be careful with this client as it bypasses tenant isolation.
    """
    return redis_pool.get_raw_client()


def get_raw_redis_replica_client() -> Redis:
    """
    Returns a Redis replica client that doesn't apply tenant prefixing to keys.

    Similar to get_raw_redis_client(), but connects to a read replica when available.
    Use this for read-heavy operations that need direct Redis access without
    tenant isolation or key prefixing.

    Warning: Be careful with this client as it bypasses tenant isolation.
    """
    return redis_pool.get_raw_replica_client()


SSL_CERT_REQS_MAP = {
    "none": ssl.CERT_NONE,
    "optional": ssl.CERT_OPTIONAL,
    "required": ssl.CERT_REQUIRED,
}


_async_redis_connection: aioredis.Redis | None = None
_async_lock = asyncio.Lock()


async def get_async_redis_connection() -> aioredis.Redis:
    """
    Provides a shared async Redis connection, using the same configs (host, port, SSL, etc.).
    Ensures that the connection is created only once (lazily) and reused for all future calls.
    """
    global _async_redis_connection

    # If we haven't yet created an async Redis connection, we need to create one
    if _async_redis_connection is None:
        # Acquire the lock to ensure that only one coroutine attempts to create the connection
        async with _async_lock:
            # Double-check inside the lock to avoid race conditions
            if _async_redis_connection is None:
                # Load env vars or your config variables

                connection_kwargs: dict[str, Any] = {
                    "host": REDIS_HOST,
                    "port": REDIS_PORT,
                    "db": REDIS_DB_NUMBER,
                    "password": REDIS_PASSWORD,
                    "max_connections": REDIS_POOL_MAX_CONNECTIONS,
                    "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL,
                    "socket_keepalive": True,
                    "socket_keepalive_options": REDIS_SOCKET_KEEPALIVE_OPTIONS,
                }

                if USE_REDIS_IAM_AUTH:
                    configure_redis_iam_auth(connection_kwargs)
                elif REDIS_SSL:
                    ssl_context = ssl.create_default_context()

                    if REDIS_SSL_CA_CERTS:
                        ssl_context.load_verify_locations(REDIS_SSL_CA_CERTS)
                    ssl_context.check_hostname = False

                    # Map your string to the proper ssl.CERT_* constant
                    ssl_context.verify_mode = SSL_CERT_REQS_MAP.get(
                        REDIS_SSL_CERT_REQS, ssl.CERT_NONE
                    )

                    connection_kwargs["ssl"] = ssl_context

                # Create a new Redis connection (or connection pool) with SSL configuration
                _async_redis_connection = aioredis.Redis(**connection_kwargs)

    # Return the established connection (or pool) for all future operations
    return _async_redis_connection


async def retrieve_auth_token_data_from_redis(request: Request) -> dict | None:
    token = request.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
    if not token:
        logger.debug("No auth token cookie found")
        return None

    try:
        redis = await get_async_redis_connection()
        redis_key = REDIS_AUTH_KEY_PREFIX + token
        token_data_str = await redis.get(redis_key)

        if not token_data_str:
            logger.debug(f"Token key {redis_key} not found or expired in Redis")
            return None

        return json.loads(token_data_str)
    except json.JSONDecodeError:
        logger.error("Error decoding token data from Redis")
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error in retrieve_auth_token_data_from_redis: {str(e)}"
        )
        raise ValueError(
            f"Unexpected error in retrieve_auth_token_data_from_redis: {str(e)}"
        )


def redis_lock_dump(lock: RedisLock, r: Redis) -> None:
    # diagnostic logging for lock errors
    name = lock.name
    ttl = r.ttl(name)
    locked = lock.locked()
    owned = lock.owned()
    local_token: str | None = lock.local.token  # type: ignore

    remote_token_raw = r.get(lock.name)
    if remote_token_raw:
        remote_token_bytes = cast(bytes, remote_token_raw)
        remote_token = remote_token_bytes.decode("utf-8")
    else:
        remote_token = None

    logger.warning(
        f"RedisLock diagnostic: "
        f"name={name} "
        f"locked={locked} "
        f"owned={owned} "
        f"local_token={local_token} "
        f"remote_token={remote_token} "
        f"ttl={ttl}"
    )
