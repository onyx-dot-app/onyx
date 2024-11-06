import functools
import threading
from collections.abc import Callable
from typing import Any
from typing import Optional

import redis
from redis.client import Redis

from danswer.configs.app_configs import REDIS_DB_NUMBER
from danswer.configs.app_configs import REDIS_HEALTH_CHECK_INTERVAL
from danswer.configs.app_configs import REDIS_HOST
from danswer.configs.app_configs import REDIS_PASSWORD
from danswer.configs.app_configs import REDIS_POOL_MAX_CONNECTIONS
from danswer.configs.app_configs import REDIS_PORT
from danswer.configs.app_configs import REDIS_SSL
from danswer.configs.app_configs import REDIS_SSL_CA_CERTS
from danswer.configs.app_configs import REDIS_SSL_CERT_REQS
from danswer.configs.constants import REDIS_SOCKET_KEEPALIVE_OPTIONS
from danswer.utils.logger import setup_logger

logger = setup_logger()


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
            "sadd",
            "srem",
            "scard",
        ]  # Regular methods that need simple prefixing

        if item == "scan_iter":
            return self._prefix_scan_iter(original_attr)
        elif item in methods_to_wrap and callable(original_attr):
            return self._prefix_method(original_attr)
        return original_attr


class RedisPool:
    _instance: Optional["RedisPool"] = None
    _lock: threading.Lock = threading.Lock()
    _pool: redis.BlockingConnectionPool

    def __new__(cls) -> "RedisPool":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(RedisPool, cls).__new__(cls)
                    cls._instance._init_pool()
        return cls._instance

    def _init_pool(self) -> None:
        self._pool = RedisPool.create_pool(ssl=REDIS_SSL)

    def get_client(self, tenant_id: str | None) -> Redis:
        if tenant_id is None:
            tenant_id = "public"
        return TenantRedis(tenant_id, connection_pool=self._pool)

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
        """We use BlockingConnectionPool because it will block and wait for a connection
        rather than error if max_connections is reached. This is far more deterministic
        behavior and aligned with how we want to use Redis."""

        # Using ConnectionPool is not well documented.
        # Useful examples: https://github.com/redis/redis-py/issues/780
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


def get_redis_client(*, tenant_id: str | None) -> Redis:
    return redis_pool.get_client(tenant_id)


# # Usage example
# redis_pool = RedisPool()
# redis_client = redis_pool.get_client()

# # Example of setting and getting a value
# redis_client.set('key', 'value')
# value = redis_client.get('key')
# print(value.decode())  # Output: 'value'
