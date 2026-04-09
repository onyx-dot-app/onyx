from typing import Generic

from fastapi import Response, status

from fastapi_users import models
from fastapi_users.authentication.strategy import (
    Strategy,
    StrategyDestroyNotSupportedError,
)
from fastapi_users.authentication.transport import (
    Transport,
    TransportLogoutNotSupportedError,
)
from fastapi_users.types import DependencyCallable


class AuthenticationBackend(Generic[models.UP, models.ID]):
    """
    Combination of an authentication transport and strategy.

    Together, they provide a full authentication method logic.

    :param name: Name of the backend.
    :param transport: Authentication transport instance.
    :param get_strategy: Dependency callable returning
    an authentication strategy instance.
    """

    name: str
    transport: Transport

    def __init__(
        self,
        name: str,
        transport: Transport,
        get_strategy: DependencyCallable[Strategy[models.UP, models.ID]],
    ):
        self.name = name
        self.transport = transport
        self.get_strategy = get_strategy

    async def login(
        self, strategy: Strategy[models.UP, models.ID], user: models.UP
    ) -> Response:
        token = await strategy.write_token(user)
        return await self.transport.get_login_response(token)

    async def logout(
        self, strategy: Strategy[models.UP, models.ID], user: models.UP, token: str
    ) -> Response:
        try:
            await strategy.destroy_token(token, user)
        except StrategyDestroyNotSupportedError:
            pass

        try:
            response = await self.transport.get_logout_response()
        except TransportLogoutNotSupportedError:
            response = Response(status_code=status.HTTP_204_NO_CONTENT)

        return response
