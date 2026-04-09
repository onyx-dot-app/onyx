from datetime import datetime
from typing import Protocol, TypeVar

from fastapi_users import models


class AccessTokenProtocol(Protocol[models.ID]):
    """Access token protocol that ORM model should follow."""

    token: str
    user_id: models.ID
    created_at: datetime


AP = TypeVar("AP", bound=AccessTokenProtocol)
