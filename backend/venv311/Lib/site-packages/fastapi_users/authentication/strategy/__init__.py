from fastapi_users.authentication.strategy.base import (
    Strategy,
    StrategyDestroyNotSupportedError,
)
from fastapi_users.authentication.strategy.db import (
    AP,
    AccessTokenDatabase,
    AccessTokenProtocol,
    DatabaseStrategy,
)
from fastapi_users.authentication.strategy.jwt import JWTStrategy

try:
    from fastapi_users.authentication.strategy.redis import RedisStrategy
except ImportError:  # pragma: no cover
    pass

__all__ = [
    "AP",
    "AccessTokenDatabase",
    "AccessTokenProtocol",
    "DatabaseStrategy",
    "JWTStrategy",
    "Strategy",
    "StrategyDestroyNotSupportedError",
    "RedisStrategy",
]
