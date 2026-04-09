from typing import Generic

import jwt

from fastapi_users import exceptions, models
from fastapi_users.authentication.strategy.base import (
    Strategy,
    StrategyDestroyNotSupportedError,
)
from fastapi_users.jwt import SecretType, decode_jwt, generate_jwt
from fastapi_users.manager import BaseUserManager


class JWTStrategyDestroyNotSupportedError(StrategyDestroyNotSupportedError):
    def __init__(self) -> None:
        message = "A JWT can't be invalidated: it's valid until it expires."
        super().__init__(message)


class JWTStrategy(Strategy[models.UP, models.ID], Generic[models.UP, models.ID]):
    def __init__(
        self,
        secret: SecretType,
        lifetime_seconds: int | None,
        token_audience: list[str] = ["fastapi-users:auth"],
        algorithm: str = "HS256",
        public_key: SecretType | None = None,
    ):
        self.secret = secret
        self.lifetime_seconds = lifetime_seconds
        self.token_audience = token_audience
        self.algorithm = algorithm
        self.public_key = public_key

    @property
    def encode_key(self) -> SecretType:
        return self.secret

    @property
    def decode_key(self) -> SecretType:
        return self.public_key or self.secret

    async def read_token(
        self, token: str | None, user_manager: BaseUserManager[models.UP, models.ID]
    ) -> models.UP | None:
        if token is None:
            return None

        try:
            data = decode_jwt(
                token, self.decode_key, self.token_audience, algorithms=[self.algorithm]
            )
            user_id = data.get("sub")
            if user_id is None:
                return None
        except jwt.PyJWTError:
            return None

        try:
            parsed_id = user_manager.parse_id(user_id)
            return await user_manager.get(parsed_id)
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

    async def write_token(self, user: models.UP) -> str:
        data = {"sub": str(user.id), "aud": self.token_audience}
        return generate_jwt(
            data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm
        )

    async def destroy_token(self, token: str, user: models.UP) -> None:
        raise JWTStrategyDestroyNotSupportedError()
