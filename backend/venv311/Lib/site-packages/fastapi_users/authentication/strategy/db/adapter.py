from datetime import datetime
from typing import Any, Generic, Protocol

from fastapi_users.authentication.strategy.db.models import AP


class AccessTokenDatabase(Protocol, Generic[AP]):
    """Protocol for retrieving, creating and updating access tokens from a database."""

    async def get_by_token(
        self, token: str, max_age: datetime | None = None
    ) -> AP | None:
        """Get a single access token by token."""
        ...  # pragma: no cover

    async def create(self, create_dict: dict[str, Any]) -> AP:
        """Create an access token."""
        ...  # pragma: no cover

    async def update(self, access_token: AP, update_dict: dict[str, Any]) -> AP:
        """Update an access token."""
        ...  # pragma: no cover

    async def delete(self, access_token: AP) -> None:
        """Delete an access token."""
        ...  # pragma: no cover
