import secrets
from typing import Generic

import redis.asyncio

from fastapi_users import exceptions, models
from fastapi_users.authentication.strategy.base import Strategy
from fastapi_users.manager import BaseUserManager


class RedisStrategy(Strategy[models.UP, models.ID], Generic[models.UP, models.ID]):
    def __init__(
        self,
        redis: redis.asyncio.Redis,
        lifetime_seconds: int | None = None,
        *,
        key_prefix: str = "fastapi_users_token:",
    ):
        self.redis = redis
        self.lifetime_seconds = lifetime_seconds
        self.key_prefix = key_prefix

    async def read_token(
        self, token: str | None, user_manager: BaseUserManager[models.UP, models.ID]
    ) -> models.UP | None:
        if token is None:
            return None

        user_id = await self.redis.get(f"{self.key_prefix}{token}")
        if user_id is None:
            return None

        try:
            parsed_id = user_manager.parse_id(user_id)
            return await user_manager.get(parsed_id)
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

    async def write_token(self, user: models.UP) -> str:
        token = secrets.token_urlsafe()
        await self.redis.set(
            f"{self.key_prefix}{token}", str(user.id), ex=self.lifetime_seconds
        )
        return token

    async def destroy_token(self, token: str, user: models.UP) -> None:
        await self.redis.delete(f"{self.key_prefix}{token}")
